#!/usr/bin/env python3
# SYNCED FILE — canonical copy: ShiftLead/dev-cadence files/scripts/cadence_config.py
# Edit it there and re-run sync.sh; an edit made in a consumer repo is overwritten (sync.sh --verify detects one).
"""The cadence's settings: the one reader every tool, skill and script goes through (TD-096).

    cadence_config.py get <key>     print the value; exit 1 when it is unset and has no default
    cadence_config.py               every known key, its value and where the value came from
    cadence_config.py --json        the same as JSON: {key: {"value": …, "from": …}}
    cadence_config.py --check       name each key no tool reads and each value of the wrong type
                                    in the files below; exit 1 when there is one

    cadence_config.py opt-outs --repo DIR
                                    the repo's opt-outs (sync.sh's reader, cadence.md Adoption
                                    checklist step 9): one TSV line per declaration,
                                    kind, value, adr, source, as-written — split by \\x1f (not
                                    a tab: bash's read would merge an empty field) — and
                                    warn\\x1f<message> for what cannot be read — always exit 0
                                    for a readable DIR, so the payload ships whole

    --repo DIR  read DIR's settings instead of the current directory's repo

Where a value comes from, the first that has it (cadence.md §9.18):
    env      CADENCE_<KEY>, the key upper-cased with `-` as `_` (CADENCE_REVIEW_MODEL);
             an empty or all-blank value counts as unset
    repo     docs/cadence.toml at the repo root (SEED: the repo owns it, sync never rewrites it)
    machine  cadence.toml in the roster's directory — $DEV_CADENCE_REG_DIR, else
             ${XDG_CONFIG_HOME:-~/.config}/dev-cadence (§9.2), so a test's override moves it too
    default  KEYS below

The files are TOML, read with `tomllib` (Python >= 3.11). **People write them; tools only
read them and never rewrite them** (cadence.md §9.18): a whole-file write drops the comments,
which are where a setting says why. Machine-written state goes to files the tools own (the
sync lock, the roster). On an older Python, a missing file is no problem, nor is one holding
only comments and blank lines (the SEED as synced); one with a setting in it is an error naming
the version — never a silent default standing in for what was written. Every file is read
before any key resolves, so an env value does not get past a file that cannot be read: fix
the file (or move it aside) rather than override around it.

Exit codes: 0 read; 1 `get` of an unset key with no default, or `--check` found something;
2 a file could not be read (bad TOML, Python too old, not a file) or an unknown key was asked
for — the message names the file or the key. Stdlib only.

Parity (cadence.md §7.9): KEYS is the reader's side; the seed `docs/cadence.toml` and §9.18
write the same keys and defaults — tests/test_cadence_config.sh holds them together.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

REPO_FILE = "docs/cadence.toml"
MACHINE_NAME = "cadence.toml"

# key -> (default, what it is). A key lands here with the first thing that reads it.
KEYS = {
    "review-model": ("sonnet", "the independent reviewer's model (§4.8): a cheaper model than the author's, never the same"),
    "sweep-model": ("sonnet", "the model the deep sweep's agents run on (/stranded-work deep)"),
    "agents": ("claude", "the agent tools whose sessions the safety nets must see, comma-separated (TD-100); without claude, the memory guard skips its Claude checks (TD-095)"),
    "forge": ("auto", "where the PRs live: auto (from origin's host), github, gitlab or none (TD-103)"),
    "worktree-root": (".claude/worktrees", "where open_worktree.sh puts worktrees, a path relative to the clone root (TD-101)"),
}


def _rel_dir(v: str) -> str:
    """worktree-root: a directory inside the clone, so every reader can join it to the root."""
    n = os.path.normpath(v.strip())
    if os.path.isabs(n) or n == "." or n == ".." or n.startswith("../") or n.startswith("~"):
        raise ValueError(f"must be a path inside the clone, relative to its root, not {v!r}")
    parts = n.split("/")
    # .git is git's; .claude itself holds settings. Glob and gitignore metacharacters would
    # make find -path, the editor's exclude and sync's .gitignore line match more than the
    # root, so the value is kept to plain names.
    if parts[0] == ".git" or n == ".claude" or any(c in n for c in "*?[]\\") or any(p[:1] in ("#", "!") for p in parts):
        raise ValueError(f"must be a plain directory path (no .git, no bare .claude, no * ? [ ] \\, no leading # or !), not {v!r}")
    return n


# key -> a function returning the value to use, or raising ValueError naming what is wrong.
# `get`, every importer through resolve(), and --check all go through it.
VALIDATE = {"worktree-root": _rel_dir}


# The opt-outs (TD-072, moved here by TD-096): tables in the repo's file, never the machine's —
# not adopting a rule is the repo's decision. Each maps a value to the ADR that decided it.
OPTOUT_TABLES = ("not-adopted", "skip-seed")
LEGACY_FILE = "docs/cadence-local.conf"   # TD-072's line grammar, still read until each repo moves
SEP = "\x1f"   # opt-outs' field separator: non-whitespace, so an empty field survives `read`


class ConfigError(Exception):
    pass


def env_name(key: str) -> str:
    return "CADENCE_" + key.upper().replace("-", "_")


def repo_root(start: str) -> str | None:
    try:
        p = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None


def machine_path() -> str:
    reg = os.environ.get("DEV_CADENCE_REG_DIR")
    if not reg:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        reg = os.path.join(base, "dev-cadence")
    return os.path.join(reg, MACHINE_NAME)


def load(path: str) -> dict | None:
    """The file's table, None when there is no file. Raises ConfigError when it cannot be read."""
    if not os.path.lexists(path):
        return None
    if not os.path.isfile(path):
        raise ConfigError(f"{path}: not a file")
    try:
        import tomllib
    except ImportError:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            raise ConfigError(f"{path}: {e}") from None
        # the SEED as synced is comments alone: nothing written, so nothing to misread
        if all(not ln.strip() or ln.lstrip().startswith("#") for ln in text.splitlines()):
            return {}
        raise ConfigError(f"{path}: reading it needs Python >= 3.11 (tomllib); this is "
                          f"{sys.version.split()[0]}") from None
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, ValueError) as e:  # tomllib.TOMLDecodeError is a ValueError
        raise ConfigError(f"{path}: {e}") from None


def sources(repo: str | None) -> list[tuple[str, dict]]:
    """(label, table) for each file that exists, highest precedence first."""
    out = []
    if repo:
        t = load(os.path.join(repo, REPO_FILE))
        if t is not None:
            out.append((REPO_FILE, t))
    mp = machine_path()
    t = load(mp)
    if t is not None:
        out.append((mp, t))
    return out


def resolve(key: str, files: list[tuple[str, dict]]) -> tuple[object, str]:
    v = (os.environ.get(env_name(key)) or "").strip()
    if v:
        return _valid(key, v, "env " + env_name(key)), "env " + env_name(key)
    for label, table in files:
        if key in table:
            v = table[key]
            if not isinstance(v, str) or not v:
                raise ConfigError(f"{label}: {key} must be a non-empty string, not {v!r}")
            return _valid(key, v, label), label
    default = KEYS[key][0]
    return default, "default" if default is not None else "unset"


def _valid(key: str, v: str, label: str) -> str:
    if key not in VALIDATE:
        return v
    try:
        return VALIDATE[key](v)
    except ValueError as e:
        raise ConfigError(f"{label}: {key} {e}") from None


def check(files: list[tuple[str, dict]]) -> list[str]:
    problems = []
    for label, table in files:
        for k, v in table.items():
            if k in OPTOUT_TABLES:
                if label != REPO_FILE:
                    problems.append(f"{label}: [{k}] is the repo's decision — put it in {REPO_FILE}; not read here")
                elif not isinstance(v, dict):
                    problems.append(f"{label}: {k} must be a table ([{k}]), not {v!r}")
                else:
                    problems += [f"{label}: [{k}] {name!r} must name its ADR as a string, not {adr!r}"
                                 for name, adr in v.items() if not isinstance(adr, str)]
            elif k not in KEYS:
                problems.append(f"{label}: unknown key '{k}' — nothing reads it (known: {', '.join(KEYS)})")
            elif not isinstance(v, str) or not v:
                problems.append(f"{label}: {k} must be a non-empty string, not {v!r}")
            elif k in VALIDATE:
                try:
                    VALIDATE[k](v)
                except ValueError as e:
                    problems.append(f"{label}: {k} {e}")
    return problems


def legacy_optouts(path: str) -> list[tuple]:
    """TD-072's `key: value — ADR` lines, read as sync.sh's bash parser read them (the same
    words in every WARN, in file order, so the move changes nothing a consumer sees): a list of
    ("opt", kind, value, why, line) and ("warn", message), in the order the file gives them."""
    if os.path.islink(path):
        return [("warn", "is a symlink — not read; nothing is opted out")]
    if not os.path.lexists(path) or os.path.isdir(path):
        return []
    try:
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            text = f.read()
    except OSError as e:  # bash died on it here; never let an opt-out drop in silence
        return [("warn", f"cannot read ({e.strerror or e}) — nothing is opted out from it")]
    out: list[tuple] = []
    for raw in text.split("\n"):   # bash's lines: \n only, never \v, \f or U+2028
        line = raw.removesuffix("\r").lstrip(" \t")
        if not line or line.startswith("#"):
            continue
        key, colon, rest = line.partition(":")
        if not colon:
            out.append(("warn", f"cannot read '{line}' — write not-adopted: §N or skip-seed: <path>"))
            continue
        if key not in OPTOUT_TABLES:
            out.append(("warn", f"cannot read '{line}' — unknown key '{key}' (not-adopted, skip-seed); ignored"))
            continue
        # `read -r val why`: split on blanks once, trim the rest's ends, keep its inner spacing
        rest = rest.strip(" \t")
        value, _, why = rest.replace("\t", " ").partition(" ")
        why = why.strip(" \t").removeprefix("—").removeprefix("-").lstrip(" \t")
        out.append(("opt", key, value, why, line))
    if any(e[0] == "opt" for e in out):
        out.append(("warn", f"is deprecated — move each line into {REPO_FILE} as a [not-adopted] or "
                            "[skip-seed] entry (cadence.md Adoption checklist step 9, TD-096); still read"))
    return out


def optouts(repo: str) -> list[str]:
    """The TSV sync.sh reads: the repo's [not-adopted]/[skip-seed] tables, then the legacy
    file's lines. A file that cannot be read is a warn line, never an exit: the caller ships
    the whole payload rather than guess (cadence.md Adoption checklist step 9)."""
    out: list[str] = []

    def clean(s: str) -> str:
        # one field: no separator or line break from the file reaches bash; spacing otherwise kept
        return "".join(" " if ch in SEP + "\t\r\n\v\f" else ch for ch in str(s)).strip()

    path = os.path.join(repo, REPO_FILE)
    try:
        table = load(path) or {}
    except ConfigError as e:
        out.append(f"warn{SEP}{REPO_FILE}: cannot read ({clean(e)}) — nothing opted out from it")
        table = {}
    for kind in OPTOUT_TABLES:
        entries = table.get(kind, {})
        if not isinstance(entries, dict):
            out.append(f"warn{SEP}{REPO_FILE}: {kind} must be a table ([{kind}]) — ignored")
            continue
        for name, adr in entries.items():
            shown = f'[{kind}] "{clean(name)}"'
            if not isinstance(adr, str):
                out.append(f"warn{SEP}{REPO_FILE}: {shown} must name its ADR as a string — ignored")
                continue
            out.append(SEP.join((kind, clean(name), clean(adr), REPO_FILE, shown)))
    for e in legacy_optouts(os.path.join(repo, LEGACY_FILE)):
        if e[0] == "warn":
            out.append(f"warn{SEP}{LEGACY_FILE}: {clean(e[1])}")
        else:
            out.append(SEP.join((e[1], clean(e[2]), clean(e[3]), LEGACY_FILE, clean(e[4]))))
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Read the cadence's settings (TD-096).")
    ap.add_argument("cmd", nargs="?", choices=["get", "opt-outs"])
    ap.add_argument("key", nargs="?")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--repo")
    a = ap.parse_args(argv)
    if a.cmd == "get" and not a.key:
        ap.error("get needs a key")
    if a.cmd == "opt-outs":
        if not a.repo or not os.path.isdir(a.repo):
            print("cadence_config: opt-outs needs --repo DIR, an existing directory", file=sys.stderr)
            return 2
        for ln in optouts(a.repo):
            print(ln)
        return 0
    if a.key and a.key not in KEYS:
        print(f"cadence_config: unknown key '{a.key}' (known: {', '.join(KEYS)})", file=sys.stderr)
        return 2
    try:
        root = repo_root(a.repo or ".")
        if a.repo and root is None:  # asked for by name: a wrong path is not "no settings"
            raise ConfigError(f"--repo {a.repo}: not a git repository")
        files = sources(root)
        if a.check:
            problems = check(files)
            for p in problems:
                print(p)
            return 1 if problems else 0
        if a.cmd == "get":
            value, _ = resolve(a.key, files)
            if value is None:
                return 1
            print(value)
            return 0
        rows = {k: dict(zip(("value", "from"), resolve(k, files))) for k in KEYS}
    except ConfigError as e:
        print(f"cadence_config: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(rows, indent=1))
    else:
        for k, r in rows.items():
            print(f"{k:<14} {r['value'] if r['value'] is not None else '-':<12} ({r['from']})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
