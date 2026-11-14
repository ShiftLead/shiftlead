"""`ao feedback report` (design §4.7 *Feedback*, *Reports from other installs*, TD-1718, TD-1794).

The shared rules of a feedback report, which the report and the intake both read: the fields and their limits,
the normalize step, the URL and email pass, the pattern pass and the 300-character cut, in that order; the names
pass, which only the report runs, since the home's names are not the reporter's; the build an install runs
(`--build`); the Markdown file; and the publish check over it. Nothing here asks the person anything: the CLI
passes in what it read (`ao`'s three listings, git, the hostname), so the scrub is code and every rule a test.
"""

from __future__ import annotations

import json
import math
import os
import re
import socket
import subprocess
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from shiftlead.feedback import UPSTREAM

AREAS = ("shiftlead", "agent-cadence", "ledgerboard")  # a finding's area, a known count's repo
MAX_FINDINGS = 40  # `new` and `known` together, both verbs
COUNT_MAX = 999  # a count over it is capped, never refused
DAYS_MAX = 366
SEATS_MAX = 999
CUT = 300  # `what` and `fix`, each, after the scrub
BODY_MAX = 65_536  # what GitHub takes in an issue's body
V = 1
MARKER = "<!-- shiftlead-feedback-report v1 -->"
TITLE = "feedback report: "
ADD_UPSTREAM = f"git remote add upstream https://github.com/{UPSTREAM} && git fetch upstream"
GIT_TIMEOUT = 60
AO_TIMEOUT = 120
CHECK_TIMEOUT = 300

# The placeholders' own words, every one of them set aside wherever it stands (pass 1).
PLACEHOLDERS = (
    "seat", "profile", "path", "project", "repo", "team", "role", "host", "user", "url", "email", "id", "secret", "ref",
)  # fmt: skip
# A name source's kinds, in the order a string two sources give takes its placeholder from.
KIND_ORDER = ("repo", "team", "project", "seat", "profile", "role", "host", "user", "path")
# The glossary's role words and the package's own roles, which no record or host's name makes a name to scrub.
ROLE_WORDS = (
    "person", "agent", "session", "worker", "manager", "techlead", "lead", "designer", "director", "member",
    "controller", "anchor", "seat", "reader", "reviewer", "grinder", "auditor", "fact-checker", "hunter", "sweeper",
    "plain",
)  # fmt: skip
ADAPTER_WORDS = ("claude", "claude-code", "gemini", "shell")
OTHER_WORDS = ("main", "home", "default", "person")
CHECKOUT_FOLDERS = ("src", "docs", "tests", "scripts", "web")  # a `dir` ending in one is a checkout's folder


def package_roles() -> frozenset[str]:
    """The roles the package itself defines: a record's or the org's role among them is no private name."""
    from shiftlead import repoconfig

    return frozenset([*repoconfig.PRESETS, *repoconfig.KINDS, *ROLE_WORDS])


def _key(name: str) -> str:
    """A name as the names pass compares it: normalized, folded, its parts joined by one `-`."""
    return "-".join(p for p in re.split(r"[-_. ]+", normalize(name).casefold()) if p)


def kept_words() -> frozenset[str]:
    """The fixed list the names pass never replaces (and the publish check is told to accept)."""
    return frozenset(_key(w) for w in [*package_roles(), *ADAPTER_WORDS, *OTHER_WORDS, *AREAS, *PLACEHOLDERS])


class Refused(ValueError):
    """Exit 2: the reason, naming at most a field, never a value."""


# ── the fields ────────────────────────────────────────────────────────────────────────────────

TD_ID = re.compile(r"TD-\d+")


def _whole(v: Any, where: str, top: int, *, cap: bool = False) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise Refused(f"{where}: bad type")
    if v < 1 or (v > top and not cap):
        raise Refused(f"{where}: not allowed")
    return min(v, top)


def _text(v: Any, where: str) -> str:
    if not isinstance(v, str):
        raise Refused(f"{where}: bad type")
    return v


def _objects(v: Any, where: str) -> list[dict[str, Any]]:
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, dict) for x in v):
        raise Refused(f"{where}: bad type")
    return v


def _td(v: Any, where: str) -> str:
    if not isinstance(v, str):
        raise Refused(f"{where}: bad type")
    if not TD_ID.fullmatch(v):
        raise Refused(f"{where}: not allowed")
    return v


def validate(data: Any) -> dict[str, Any]:
    """The findings file's fields, kept and checked (§4.7 *`ao feedback report`*): any other key is dropped; a
    type, shape or allowed value broken is refused; a count over 999 capped. Raises `Refused`."""
    if not isinstance(data, dict):
        raise Refused("the findings file: bad type")
    noise = data.get("noise")
    if isinstance(noise, bool) or not isinstance(noise, int | float):
        raise Refused("noise: bad type")
    if not 0 <= noise <= 1 or not math.isfinite(noise):  # the range first: a huge int overflows a float
        raise Refused("noise: not allowed")
    new = []
    for i, f in enumerate(_objects(data.get("new"), "new")):
        area = _text(f.get("area"), f"new[{i}].area")
        if area not in AREAS:
            raise Refused(f"new[{i}].area: not allowed")
        recurs = f.get("recurs")
        new.append(
            {
                "area": area,
                "what": _text(f.get("what"), f"new[{i}].what"),
                "fix": _text(f.get("fix"), f"new[{i}].fix"),
                "count": _whole(f.get("count"), f"new[{i}].count", COUNT_MAX, cap=True),
                "recurs": None if recurs is None else _td(recurs, f"new[{i}].recurs"),
            }
        )
    known = []
    for i, k in enumerate(_objects(data.get("known"), "known")):
        repo = _text(k.get("repo"), f"known[{i}].repo")
        if repo not in AREAS:
            raise Refused(f"known[{i}].repo: not allowed")
        known.append(
            {
                "repo": repo,
                "id": _td(k.get("id"), f"known[{i}].id"),
                "count": _whole(k.get("count"), f"known[{i}].count", COUNT_MAX, cap=True),
            }
        )
    names = data.get("names") or []
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise Refused("names: bad type")
    n = len(new) + len(known)
    if not n:
        raise Refused("no new and no known finding: there is nothing to report")
    if n > MAX_FINDINGS:
        raise Refused(f"{n} findings: a report holds at most {MAX_FINDINGS}, new and known together")
    return {
        "days": _whole(data.get("days"), "days", DAYS_MAX),
        "seats": _whole(data.get("seats"), "seats", SEATS_MAX),
        "noise": round(float(noise), 2),
        "new": new,
        "known": known,
        "names": names,
    }


# ── the text: normalize, three passes, the cut ───────────────────────────────────────────────

# A set-aside span stands in the text as one character of plane 15's private use area: no space, no letter or
# digit, so a path run goes on through it, no name or pattern reads inside it, and it is no path's left edge.
_SENT0 = 0xF0000
_SENT = "\U000f0000-\U000ffffd"
_SENT_RE = re.compile(f"[{_SENT}]")


def normalize(text: str) -> str:
    """NFKC; every whitespace character a space; every remaining Cc, Cf and Cs character dropped (a lone surrogate
    no output encodes); backticks `'`, and
    `](` made `] (`. (A plane-15 private-use character is dropped too: it is the scrub's own set-aside mark.)"""
    t = unicodedata.normalize("NFKC", text)
    t = "".join(" " if c.isspace() else c for c in t)
    t = "".join(c for c in t if unicodedata.category(c) not in ("Cc", "Cf", "Cs") and not _SENT_RE.match(c))
    return t.replace("`", "'").replace("](", "] (")


@dataclass
class _Text:
    """The text being scrubbed, and what it set aside."""

    text: str
    kept: list[str] = field(default_factory=list)

    def aside(self, value: str) -> str:
        self.kept.append(value)
        return chr(_SENT0 + len(self.kept) - 1)

    def sub(self, pattern: re.Pattern[str], repl: Callable[[re.Match[str]], str]) -> None:
        self.text = pattern.sub(lambda m: self.aside(repl(m)), self.text)

    def finish(self, cut: int = CUT) -> str:
        """Every set-aside span put back, the text cut to `cut` characters, backing up before a span it would
        split (a placeholder, a kept URL or ref)."""
        out: list[str] = []
        n = 0
        for c in self.text:
            piece = self.kept[ord(c) - _SENT0] if _SENT_RE.match(c) else c
            if n + len(piece) > cut:
                break
            out.append(piece)
            n += len(piece)
        return "".join(out)


_PLACEHOLDER_RE = re.compile("<(?:" + "|".join(PLACEHOLDERS) + ")>")
_URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S*")
_KEPT_URL_RE = re.compile(r"https://github\.com/ShiftLead/[A-Za-z0-9._/-]*")
_SCP_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+:\S+")
_EMAIL_RE = re.compile(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)+")  # the publish check's own, or wider
_IPV4_RE = re.compile(r"(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?!\w|\.\d)")
_IPV6_RE = re.compile(r"\[[0-9A-Fa-f:]*:[\w:.%]*\]")
_PATH_RE = re.compile(rf"(?<![\w\-./{_SENT}])(?:~/|\$HOME/|\$\{{HOME\}}/|/)\S*")
_ID_RE = re.compile(
    r"(?<![^\W_])(?:m-[0-9a-f]{12}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    r"(?![^\W_])"
)
_SECRET_RE = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{32,}")
_REPO_REF_RE = re.compile(r"(?<![\w.-])([A-Za-z0-9_.-]+)#TD-\d+(?!\d)", re.IGNORECASE)
_KEPT_NUMBER_RE = re.compile(r"(?<![\w.-])(?:" + "|".join(AREAS) + r")#\d+(?!\d)", re.IGNORECASE)  # not bare
_BARE_REF_RE = re.compile(r"(?:(?<![\w-])TD-\d+|#\d+)(?!\d)", re.IGNORECASE)


def _urls(t: _Text) -> None:
    """Pass 1: placeholders already there, URLs (a ShiftLead one kept whole), git's scp form, emails, addresses."""
    t.sub(_PLACEHOLDER_RE, lambda m: m.group(0))
    t.sub(_URL_RE, lambda m: m.group(0) if _KEPT_URL_RE.fullmatch(m.group(0)) else "<url>")
    t.sub(_SCP_RE, lambda m: "<url>")
    t.sub(_EMAIL_RE, lambda m: "<email>")
    t.sub(_IPV4_RE, lambda m: "<host>")
    t.sub(_IPV6_RE, lambda m: "<host>")


def _patterns(t: _Text, keep_ids: Iterable[str]) -> None:
    """Pass 3, in order: paths, mail ids and UUIDs, 32-character runs, other repos' refs, bare ids."""
    keep = {i.upper() for i in keep_ids}
    t.sub(_PATH_RE, lambda m: "<path>")
    t.sub(_ID_RE, lambda m: "<id>")
    t.sub(_SECRET_RE, lambda m: "<secret>")
    t.sub(_REPO_REF_RE, lambda m: m.group(0) if m.group(1).casefold() in AREAS else "<ref>")
    t.sub(_KEPT_NUMBER_RE, lambda m: m.group(0))
    t.sub(_BARE_REF_RE, lambda m: m.group(0) if m.group(0).upper() in keep else "<ref>")


@dataclass(frozen=True)
class Names:
    """The names pass's alternation (§4.7 pass 2): every known name, longest first, and its placeholder."""

    pattern: re.Pattern[str] | None
    kinds: dict[str, str]  # a name's `_key` -> its placeholder's word

    @classmethod
    def of(cls, pairs: Iterable[tuple[str, str]]) -> Names:
        keep = kept_words()
        kinds: dict[str, str] = {}
        texts: dict[str, str] = {}
        rank = {k: i for i, k in enumerate(KIND_ORDER)}
        for name, kind in pairs:
            if not isinstance(name, str):
                continue
            key = _key(name)
            if len(key) < 3 or key in keep:
                continue
            if key not in kinds or rank[kind] < rank[kinds[key]]:
                kinds[key] = kind
            texts[key] = "[-_. ]".join(re.escape(p) for p in key.split("-"))
        if not kinds:
            return cls(None, {})
        alts = [texts[k] for k in sorted(kinds, key=lambda k: (-len(k), k))]
        return cls(re.compile(r"(?<![^\W_])(?:" + "|".join(alts) + r")(?![^\W_])"), kinds)

    def apply(self, t: _Text) -> None:
        """Each name replaced, matched on the folded text, the replacement made on the unfolded one."""
        if self.pattern is None:
            return
        folded: list[str] = []
        owner: list[int] = []  # the original character each folded one came from
        first: set[int] = set()  # the folded positions that open an original character
        for i, c in enumerate(t.text):
            f = c.casefold()
            first.add(len(owner))
            folded.append(f)
            owner.extend([i] * len(f))
        text = "".join(folded)
        first.add(len(text))
        spans: list[tuple[int, int, str]] = []
        for m in self.pattern.finditer(text):
            a, b = m.span()
            if a == b or a not in first or b not in first:
                continue  # a match that would split a character's folding is no match
            kind = self.kinds.get(_key(m.group(0)))
            if kind:
                spans.append((owner[a], owner[b - 1] + 1, kind))
        for a, b, kind in reversed(spans):
            t.text = t.text[:a] + t.aside(f"<{kind}>") + t.text[b:]


def shared(text: str, keep_ids: Iterable[str] = ()) -> str:
    """The rules the intake runs too, without the names pass: normalize, pass 1, pass 3, the cut."""
    return scrub(text, Names(None, {}), keep_ids)


def scrub(text: str, names: Names, keep_ids: Iterable[str] = ()) -> str:
    """Normalize, then the three passes, then the cut (§4.7 *`ao feedback report`*)."""
    t = _Text(normalize(text))
    _urls(t)
    names.apply(t)
    _patterns(t, keep_ids)
    return t.finish()


# ── the names an install's scrub knows ───────────────────────────────────────────────────────


def _last(path: Any) -> str | None:
    if not isinstance(path, str) or not path.strip():
        return None
    return Path(path.rstrip("/")).name or None


def name_pairs(
    status: Any,
    org: Any,
    repos: Any,
    names: Sequence[str] = (),
    *,
    hostname: str = "",
    user: Sequence[str] = (),
) -> list[tuple[str, str]]:
    """Every (name, placeholder word) the names pass replaces: `ao status --json`'s records (closed ones among
    them), the findings file's `names`, `ao org --json`'s teams and roles, `ao repo --all --json`'s repos, the
    hosts, this machine's hostname with its first label and that label's part before a `-`, and the person's
    own names (`user`: `$USER`, git's user.name and its words, user.email and its part before `@`)."""
    own = package_roles()
    out: list[tuple[str, str]] = []

    def add(value: Any, kind: str) -> None:
        if isinstance(value, str) and value.strip():
            out.append((value, kind))

    for r in status if isinstance(status, list) else []:
        if not isinstance(r, dict):
            continue
        add(r.get("id"), "seat")
        add(r.get("name"), "seat")
        add(r.get("profile"), "profile")
        add(r.get("worktree"), "path")
        add(r.get("project"), "project")
        add(r.get("team"), "team")
        if r.get("role") not in own:
            add(r.get("role"), "role")
        repo = _last(r.get("repo"))
        if repo not in AREAS:
            add(repo, "repo")
        d = _last(r.get("dir"))
        if d not in CHECKOUT_FOLDERS:
            add(d, "path")
        add(r.get("host"), "host")
    for n in names:
        add(n, "seat")
    org = org if isinstance(org, dict) else {}
    for t in org.get("teams") or []:
        if not isinstance(t, dict):
            continue
        add(t.get("name"), "team")
        add(t.get("project"), "project")
        repo = _last(t.get("repo"))
        if repo not in AREAS:
            add(repo, "repo")
        add(t.get("host"), "host")
    for r in org.get("roles") or []:
        if isinstance(r, dict) and r.get("name") not in own:
            add(r.get("name"), "role")
    for r in repos if isinstance(repos, list) else []:
        if not isinstance(r, dict):
            continue
        if r.get("name") not in AREAS:
            add(r.get("name"), "repo")
        add(_last(r.get("root")), "path")
    if hostname:
        label = hostname.split(".")[0]
        for h in (hostname, label, label.split("-")[0]):
            add(h, "host")
    for u in user:
        add(u, "user")
    return out


AoRun = Callable[[Sequence[str]], Any]
GitRun = Callable[..., subprocess.CompletedProcess[str]]


def run_ao(args: Sequence[str]) -> Any:
    """`ao <args> --json`, from this install; its JSON, or `Refused` where it fails (exits non-zero, prints
    `{"error": …}` or no JSON): a scrub missing its names is no scrub."""
    import sys

    cmd = [sys.executable, "-m", "shiftlead.cli", *args, "--json"]
    what = "ao " + " ".join([*args, "--json"])
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=AO_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Refused(f"{what}: {e}") from None
    try:
        got = json.loads(cp.stdout)
    except ValueError:
        got = None
    if cp.returncode != 0 or got is None or (isinstance(got, dict) and "error" in got):
        why = got.get("error") if isinstance(got, dict) else None
        why = why or ((cp.stderr or "").strip().splitlines() or [f"exit {cp.returncode}"])[-1]
        raise Refused(f"{what} failed: {why}")
    return got


def git(cwd: str | Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=GIT_TIMEOUT)


def user_names(env: dict[str, str] | None = None, run: GitRun = git) -> list[str]:
    """`$USER`, git's global user.name and each word of it, user.email and its part before `@`, each skipped
    when unset."""
    env = os.environ if env is None else env
    out = [env["USER"]] if env.get("USER") else []
    for key in ("user.name", "user.email"):
        try:
            cp = run(Path.home(), "config", "--global", "--get", key)
        except (OSError, subprocess.TimeoutExpired):
            continue
        value = cp.stdout.strip() if cp.returncode == 0 else ""
        if not value:
            continue
        out.append(value)
        out += value.split() if key == "user.name" else [value.split("@")[0]]
    return out


def gather_names(names: Sequence[str], ao: AoRun = run_ao, *, env: dict[str, str] | None = None) -> Names:
    """The names pass for this install: `ao`'s three listings (a failure is `Refused`), the hostname and the
    person's own names."""
    status = ao(["status"])
    org = ao(["org"])
    repos = ao(["repo", "--all"])
    pairs = name_pairs(status, org, repos, names, hostname=socket.gethostname(), user=user_names(env))
    return Names.of(pairs)


# ── the build ────────────────────────────────────────────────────────────────────────────────


def remote_key(url: str) -> tuple[str, str] | None:
    """A remote as *The mode* compares it: host and `owner/name`, from the https, `ssh://` or scp form, any
    `user:token@` and a port dropped, a trailing `.git` dropped, case ignored; GitHub's three hosts one."""
    u = url.strip()
    m = re.match(r"(?i)^[a-z][a-z0-9+.-]*://(?:[^@/]*@)?([^/:@]+)(?::\d*)?/(.+)$", u) or re.match(
        r"^(?:[^@/\s]+@)?([^/:@\s]+):(?!//)(.+)$", u
    )
    if not m:
        return None
    host, path = m.group(1).lower(), m.group(2).strip("/")
    if path.lower().endswith(".git"):
        path = path[:-4]
    if host in ("www.github.com", "ssh.github.com"):
        host = "github.com"
    return host, path.casefold()


def is_upstream(url: str) -> bool:
    return remote_key(url) == ("github.com", UPSTREAM.casefold())


def direct_url() -> str | None:
    """The installed `shiftlead`'s `direct_url.json`, as text (None where there is none)."""
    from importlib import metadata

    try:
        return metadata.distribution("shiftlead").read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        return None


def read_build(raw: str | None, run: GitRun = git) -> dict[str, Any]:
    """`--build` (§4.7 *The build the install runs*): `{checkout, commit, build_day, local}`, or `Refused`."""
    url = ""
    if raw:
        try:
            url = json.loads(raw).get("url") or ""
        except (ValueError, AttributeError):
            url = ""
    parts = urlsplit(url) if isinstance(url, str) else None
    if not parts or parts.scheme != "file":
        raise Refused("no checkout: this shiftlead was not installed from a directory (direct_url.json)")
    checkout = unquote(parts.path)
    if not Path(checkout).is_dir():
        raise Refused(f"no checkout: {checkout} is not a directory")

    def call(*args: str) -> subprocess.CompletedProcess[str]:
        try:
            cp = run(checkout, *args)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise Refused(f"git {args[0]} in {checkout} failed: {e}") from None
        return cp

    def ok(*args: str) -> str:
        cp = call(*args)
        if cp.returncode != 0:
            why = ((cp.stderr or "").strip().splitlines() or [f"exit {cp.returncode}"])[-1]
            raise Refused(f"git {' '.join(args)} in {checkout} failed: {why}")
        return cp.stdout.strip()

    if call("rev-parse", "--git-dir").returncode != 0:
        raise Refused(f"no checkout: {checkout} holds no git checkout")
    fetch: dict[str, str] = {}
    for line in ok("remote", "-v").splitlines():
        bits = line.split()
        if len(bits) >= 3 and bits[2] == "(fetch)":
            fetch.setdefault(bits[0], bits[1])
    remote = next((r for r in ok("remote").splitlines() if is_upstream(fetch.get(r, ""))), None)
    if remote is None:
        seen = ", ".join(f"{r} {u}" for r, u in fetch.items()) or "none"
        raise Refused(f"{checkout}: no remote's URL is {UPSTREAM} (remotes: {seen}); add it there: {ADD_UPSTREAM}")
    ref = f"refs/remotes/{remote}/main"
    if call("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode != 0:
        raise Refused(f"{checkout}: no main under {remote} ({ref}); fetch it there: git fetch {remote}")
    head = ok("rev-parse", "HEAD")
    anc = call("merge-base", "--is-ancestor", "HEAD", ref)
    if anc.returncode not in (0, 1):
        raise Refused(f"git merge-base --is-ancestor HEAD {ref} in {checkout} failed")
    local = anc.returncode == 1
    commit = ok("merge-base", "HEAD", ref) if local else head
    return {
        "checkout": checkout,
        "commit": commit,
        "build_day": ok("log", "-1", "--format=%cs", commit),
        "local": local,
    }


# ── the report ───────────────────────────────────────────────────────────────────────────────


def scrubbed(findings: dict[str, Any], names: Names) -> dict[str, Any]:
    """The findings with each `what` and `fix` normalized, scrubbed and cut; `names` gone."""
    known_ids = [k["id"] for k in findings["known"]]
    new = [
        {
            **f,
            "what": scrub(f["what"], names, [*known_ids, *([f["recurs"]] if f["recurs"] else [])]),
            "fix": scrub(f["fix"], names, [*known_ids, *([f["recurs"]] if f["recurs"] else [])]),
        }
        for f in findings["new"]
    ]
    return {k: findings[k] for k in ("days", "seats", "noise")} | {"new": new, "known": findings["known"]}


def _cell(text: str) -> str:
    """One code span, its `|` escaped as a table needs; an empty text an empty cell."""
    return f"`{text.replace('|', chr(92) + '|')}`" if text.strip() else ""


def render(report: dict[str, Any], commit: str, build_day: str) -> str:
    """The report's Markdown (§4.7 *The report's shape*): the title, the table, the marker, the block."""
    n = len(report["new"]) + len(report["known"])
    lines = [f"{TITLE}{commit[:7]} · {n} findings", "", "| area | what | fix | count | |", "|---|---|---|---|---|"]
    for f in report["new"]:
        tail = f"recurs {f['recurs']}" if f["recurs"] else ""
        lines.append(f"| {f['area']} | {_cell(f['what'])} | {_cell(f['fix'])} | {f['count']} | {tail} |")
    for k in report["known"]:
        lines.append(f"| {k['repo']} | – | – | {k['count']} | seen on {k['id']} |")
    block = {"v": V, "commit": commit, "build_day": build_day, **report}
    block = {k: block[k] for k in ("v", "commit", "build_day", "days", "seats", "noise", "new", "known")}
    body = json.dumps(block, ensure_ascii=False, indent=1)
    return "\n".join([*lines, "", MARKER, "", "```json", body, "```", ""])


def _ci_glob(word: str) -> str:
    return "".join(f"[{c.upper()}{c.lower()}]" if c.isalpha() else c for c in word)


def accept_lines() -> list[str]:
    """The accept file: `shiftlead`, `ledgerboard` and each fixed-list word, in any case, whole in the finding's
    own parentheses, whatever kind the check gives it."""
    words = sorted({"shiftlead", "ledgerboard", *(w for w in kept_words() if w != "agent-cadence")})
    return [f"* * ({_ci_glob(w)})" for w in words]


def publish_check(checkout: str, out: str, run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run):
    """`agent-cadence -C <checkout> run cadence_layer.py --publish-check --accept <out>.accept <out>`: (exit, its
    `path:line: finding` lines). An exit other than 0 or 1, or no `agent-cadence`, is `Refused`."""
    accept = out + ".accept"
    Path(accept).write_text("\n".join(accept_lines()) + "\n", encoding="utf-8")
    cmd = ["agent-cadence", "-C", checkout, "run", "cadence_layer.py", "--publish-check", "--accept", accept, out]
    try:
        cp = run(cmd, capture_output=True, text=True, timeout=CHECK_TIMEOUT)
    except FileNotFoundError:
        raise Refused("the publish check cannot run: no agent-cadence on PATH") from None
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Refused(f"the publish check cannot run: {e}") from None
    finally:
        Path(accept).unlink(missing_ok=True)
    if cp.returncode == 0:
        return 0, []
    if cp.returncode == 1:
        mine = re.compile(r"\S.*?:\d+: ")  # its `path:line: finding` lines, whatever spelling of the path
        return 1, [line for line in (cp.stdout or "").splitlines() if mine.match(line)]
    why = ((cp.stderr or "").strip().splitlines() or [f"exit {cp.returncode}"])[-1]
    raise Refused(f"the publish check cannot run (exit {cp.returncode}): {why}")


def report(
    findings_path: str,
    out_path: str,
    *,
    build: Callable[[], dict[str, Any]] | None = None,
    names: Callable[[Sequence[str]], Names] | None = None,
    check: Callable[[str, str], tuple[int, list[str]]] | None = None,
) -> dict[str, Any]:
    """`ao feedback report --findings <file> --out <file.md>`: `{out, commit, build_day, local, check: {exit,
    lines}}`, or `Refused` with `<out>` removed. The three callables are the build read, the name sources and
    the publish check, which a test hands in."""
    out = os.path.abspath(out_path)
    try:
        try:
            raw = Path(findings_path).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as e:
            raise Refused(f"the findings file cannot be read: {getattr(e, 'strerror', None) or e}") from None
        try:
            data = json.loads(raw)
        except ValueError:
            raise Refused("the findings file does not parse as JSON") from None
        findings = validate(data)
        b = (build or (lambda: read_build(direct_url())))()
        got = scrubbed(findings, (names or gather_names)(findings["names"]))
        text = render(got, b["commit"], b["build_day"])
        if len(text) > BODY_MAX:
            raise Refused(f"report over {BODY_MAX} characters")
        Path(out).write_text(text, encoding="utf-8")
        code, lines = (check or (lambda c, o: publish_check(c, o)))(os.path.abspath(b["checkout"]), out)
    except Refused:
        Path(out).unlink(missing_ok=True)
        raise
    return {
        "out": out,
        "commit": b["commit"],
        "build_day": b["build_day"],
        "local": b["local"],
        "check": {"exit": code, "lines": lines},
    }
