#!/usr/bin/env python3
"""The pre-review script (design §4.9c *What a design's author prepares before a review*, TD-1755).

    pdm run python scripts/design_prep.py --entry TD-<design> [--rev <commit>] [--base <commit>] [--advisory]

Checks a design at a commit, never at a work tree: the prep file `docs/reviews/TD-<design>.prep.yml` and the
design's text are read in a temporary detached worktree of the commit, added to the repository of the worktree the
script runs from and removed when it ends. Four checks, in the section's order — rules, claims, pointers, tools —
and one pass line, whose first word every reviewer reads first:

    design-prep: PASS · TD-<design> · <commit> · base <commit> · claims <n> · rules <n> · new <n> · waived <n>  (exit 0)
    design-prep: FAIL · …, then one line per flag, `<check> · <file>:<line> · <what>`                            (exit 1)
    design-prep: NOT PREPARED · <why>                                                                         (exit 2)
    design-prep: CANNOT RUN · <why>                                                                           (exit 3)

`--advisory` prints the same lines under `design-prep: ADVISORY · …` and exits 0.
"""

from __future__ import annotations

import argparse
import bisect
import glob
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PREFIX = "design-prep-"  # every temporary worktree's name starts so; a stale one is ours to remove
GIT_TIMEOUT = 120
TOOL_TIMEOUT = 300  # each tool, five minutes
CHANGED_PATHS = ("docs/design", "docs/briefs", "docs/ledger", "docs/synopses", "docs/glossary.md")
RULE_DIRS = ("docs/design", "docs/briefs", "docs/synopses")
GLOSSARY = "docs/glossary.md"
DOC_TESTS = ("tests/test_synopses.py", "tests/test_design_doc.py", "tests/test_history.py")
CHECKS = ("rules", "claims", "pointers", "tools")
SKIP_WORDS = {"cadence", "adr", "spec", "rationale"}  # a § after these is another document's

FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
FIELD_RE = re.compile(r"^\*\*[A-Z][A-Za-z0-9 ()/-]*:\*\*")  # a ledger entry's `**Field:**`
TOP_ITEM_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s+")  # a top-level list item, at column 0
PATH_RUN_RE = re.compile(r"[A-Za-z0-9_./-]+")
EXT_RE = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,7}$")
LINK_TARGET_RE = re.compile(r"\]\(([^)\s]+)\)")
SECTION_RE = re.compile(r"§(\d+(?:\.\d+)*[a-z]?)")
TITLE_AFTER_RE = re.compile(r"\s+\*(?!\*)([^*]+?)\*(?!\*)")
TD_RE = re.compile(r"(?<![A-Za-z0-9])TD-(\d+)(?![0-9])")
INDEX_RE = re.compile(r"\*\*§([0-9][0-9.]*[a-z]?)\*\*\s*\[[^\]]*\]\(([^)\s]+)\)")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
HEADING_RE = re.compile(r"^#+\s+(.*)$", re.MULTILINE)
LIST_GAP_RE = re.compile(r"\s*(?:,\s*(?:and\s+|or\s+)?|\s(?:and|or)\s+)")


class NotPrepared(Exception):
    """What the author controls and mends: exit 2, decided before any check runs."""


class CannotRun(Exception):
    """A commit or base that cannot be resolved, or the script's own fault: exit 3."""


@dataclass
class Flag:
    check: str
    file: str
    line: int
    text: str  # what a waiver names to hide it
    what: str
    rule: str | None = None  # set on a rule's paragraph flag, which a waiver matches by its opening
    hideable: bool = True

    def render(self) -> str:
        return f"{self.check} · {self.file}:{self.line} · {self.what}"


@dataclass
class Para:
    """A paragraph: its file, the line it starts on, and its text with each whitespace run read as one space."""

    file: str
    line: int
    text: str
    offsets: list[int] = field(default_factory=list)  # where each source line starts in `text`
    lines: list[int] = field(default_factory=list)  # that source line's number

    def line_at(self, offset: int) -> int:
        return self.lines[max(0, bisect.bisect_right(self.offsets, offset) - 1)]


def collapse(s: str) -> str:
    return " ".join(str(s).split())


def git(cwd: Path, *args: str, check: bool = True) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=GIT_TIMEOUT, check=False)
    except subprocess.TimeoutExpired as e:
        raise CannotRun(f"git {args[0]} timed out") from e
    if check and r.returncode != 0:
        raise CannotRun(f"git {' '.join(args[:2])}: {collapse(r.stderr) or 'exit ' + str(r.returncode)}")
    return r.stdout


# --- paragraphs ---------------------------------------------------------------------------------------------------


def fenced_lines(lines: list[str]) -> set[int]:
    """1-based numbers of the lines in fenced blocks, their fences included (to the end when unclosed)."""
    out: set[int] = set()
    opened: str | None = None
    for i, raw in enumerate(lines, 1):
        m = FENCE_RE.match(raw)
        if opened is None:
            if m:
                opened = m.group(1)
                out.add(i)
        else:
            out.add(i)
            if (
                m
                and m.group(1)[0] == opened[0]
                and len(m.group(1)) >= len(opened)
                and not raw.strip()[len(m.group(1)) :]
            ):
                opened = None
    return out


def _para(file: str, chunk: list[tuple[int, str]]) -> Para | None:
    p = Para(file, chunk[0][0] if chunk else 0, "")
    parts: list[str] = []
    at = 0
    for n, raw in chunk:
        s = collapse(raw)
        if not s:
            continue
        if parts:
            at += 1
        p.offsets.append(at)
        p.lines.append(n)
        parts.append(s)
        at += len(s)
    if not parts:
        return None
    p.text = " ".join(parts)
    p.line = p.lines[0]
    return p


def paragraphs(file: str, text: str, ledger: bool = False) -> list[Para]:
    """A block between blank lines, except that each top-level list item with its continuation lines, each table
    row and each heading is one of its own, and in a ledger entry each `**Field:**` body is one. Fenced blocks are
    left out."""
    lines = text.split("\n")
    fenced = fenced_lines(lines)
    out: list[Para] = []
    cur: list[tuple[int, str]] = []
    in_field = False

    def flush() -> None:
        nonlocal cur
        p = _para(file, cur)
        if p:
            out.append(p)
        cur = []

    for i, raw in enumerate(lines, 1):
        if i in fenced:
            if not (ledger and in_field):
                flush()
            continue
        if ledger and (FIELD_RE.match(raw) or raw.startswith("#")):
            flush()
            in_field = bool(FIELD_RE.match(raw))
            cur = [(i, raw)]
            if not in_field:
                flush()
            continue
        if ledger and in_field:
            cur.append((i, raw))
            continue
        if not raw.strip():
            flush()
        elif raw.startswith("|"):
            flush()
            cur = [(i, raw)]
            flush()
        elif TOP_ITEM_RE.match(raw):
            flush()
            cur = [(i, raw)]
        else:
            cur.append((i, raw))
    flush()
    return out


def is_ledger(rel: str) -> bool:
    return rel.startswith("docs/ledger/")


# --- the prep file --------------------------------------------------------------------------------------------------


@dataclass
class Prep:
    path: str
    raw: str
    claims: list[dict]
    rules: list[dict]
    new: list[dict]
    waive: list[dict]

    def line_of(self, text: str) -> int:
        for i, line in enumerate(self.raw.split("\n"), 1):
            if text and str(text) in line:
                return i
        return 1


def _items(data: dict, key: str, allowed: set[str], required: set[str]) -> list[dict]:
    items = data.get(key) or []
    if not isinstance(items, list):
        raise NotPrepared(f"the prep file's {key} is not a list")
    for n, it in enumerate(items, 1):
        if not isinstance(it, dict):
            raise NotPrepared(f"{key} item {n} is not a mapping")
        unknown = set(it) - allowed
        if unknown:
            raise NotPrepared(f"{key} item {n} has an unknown key: {', '.join(sorted(unknown))}")
        missing = required - set(it)
        if missing:
            raise NotPrepared(f"{key} item {n} lacks {', '.join(sorted(missing))}")
        for k in set(it) & {"says", "at", "has", "name", "find", "path", "by", "check", "rule", "file", "text", "why"}:
            if not isinstance(it[k], str) or not it[k].strip():
                raise NotPrepared(f"{key} item {n}'s {k} is not a non-empty string")
    return items


def load_prep(rel: str, raw: str) -> Prep:
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise NotPrepared(f"{rel} is not YAML: {collapse(e)}") from e
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise NotPrepared(f"{rel} is not a mapping of claims, rules, new and waive")
    unknown = set(data) - {"claims", "rules", "new", "waive"}
    if unknown:
        raise NotPrepared(f"{rel} has an unknown key: {', '.join(sorted(map(str, unknown)))}")
    claims = _items(data, "claims", {"says", "at", "has", "count", "is"}, {"says"})
    for n, c in enumerate(claims, 1):
        if ("at" in c) == ("count" in c):
            raise NotPrepared(f"claims item {n} needs one of at or count")
        if "at" in c:
            if "is" in c:
                raise NotPrepared(f"claims item {n}: is goes with count, not at")
            at_path = re.sub(r":\d+$", "", c["at"]).removeprefix("agent-cadence:")
            if at_path.startswith("/") or ".." in at_path.split("/"):
                raise NotPrepared(f"claims item {n}'s at leaves the repo")
        else:
            if "has" in c:
                raise NotPrepared(f"claims item {n}: has goes with at, not count")
            cnt = c["count"]
            if not isinstance(cnt, dict) or not isinstance(cnt.get("glob"), str) or not cnt["glob"].strip():
                raise NotPrepared(f"claims item {n}'s count needs a glob")
            if cnt["glob"].startswith("/") or ".." in cnt["glob"].split("/"):
                raise NotPrepared(f"claims item {n}'s glob leaves the repo")
            if set(cnt) - {"glob", "grep", "lines"}:
                raise NotPrepared(f"claims item {n}'s count has an unknown key")
            if "grep" in cnt:
                if not isinstance(cnt["grep"], str):
                    raise NotPrepared(f"claims item {n}'s grep is not a string")
                try:
                    re.compile(cnt["grep"])
                except re.error as e:
                    raise NotPrepared(f"claims item {n}'s grep is not a regex: {e}") from e
            if "lines" in cnt and not isinstance(cnt["lines"], bool):
                raise NotPrepared(f"claims item {n}'s lines is not true or false")
            if not isinstance(c.get("is"), int) or isinstance(c.get("is"), bool):
                raise NotPrepared(f"claims item {n}'s count needs an integer is")
    rules = _items(data, "rules", {"name", "find", "terms"}, {"name", "find", "terms"})
    for n, r in enumerate(rules, 1):
        try:
            re.compile(r["find"])
        except re.error as e:
            raise NotPrepared(f"rules item {n}'s find is not a regex: {e}") from e
        terms = r["terms"]
        if not isinstance(terms, list) or not terms or not all(isinstance(t, str) and t.strip() for t in terms):
            raise NotPrepared(f"rules item {n}'s terms is not a list of words")
    names = [r["name"] for r in rules]
    if len(set(names)) != len(names):
        raise NotPrepared("two rules share a name")
    new = _items(data, "new", {"path", "by"}, {"path", "by"})
    for n, it in enumerate(new, 1):
        if not re.fullmatch(r"TD-\d+", it["by"]):
            raise NotPrepared(f"new item {n}'s by is not a TD-<n>")
    waive = _items(data, "waive", {"check", "rule", "file", "text", "why"}, {"check", "file", "text"})
    for n, w in enumerate(waive, 1):
        if w["check"] not in CHECKS:
            raise NotPrepared(f"waive item {n}'s check is not one of {', '.join(CHECKS)}")
        if "rule" in w and w["check"] != "rules":
            raise NotPrepared(f"waive item {n} names a rule but waives {w['check']}")
        if w["check"] == "rules" and w["file"] != rel and "rule" not in w:
            raise NotPrepared(f"waive item {n} waives a rule's paragraph but names no rule")
    return Prep(rel, raw, claims, rules, new, waive)


def check_waiver_floor(prep: Prep, paras_by_file: dict[str, list[Para]]) -> None:
    """A rule waiver on a paragraph names text of at least eight words, or the whole paragraph."""
    for n, w in enumerate(prep.waive, 1):
        if w["check"] != "rules" or w["file"] == prep.path:
            continue
        text = collapse(w["text"])
        if len(text.split()) >= 8:
            continue
        if any(p.text == text for p in paras_by_file.get(w["file"], [])):
            continue
        raise NotPrepared(f"waive item {n}'s text is under eight words and not a whole paragraph of {w['file']}")


# --- the commit's text ----------------------------------------------------------------------------------------------


def read(tree: Path, rel: str) -> str | None:
    p = tree / rel
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def added_lines(top: Path, base: str, commit: str) -> dict[str, set[int]]:
    """The lines the PR adds against the base, by file, in the changed-text paths."""
    out: dict[str, set[int]] = {}
    diff = git(
        top,
        "-c",
        "core.quotepath=off",
        "diff",
        "--unified=0",
        "--no-color",
        "--no-renames",
        "--no-ext-diff",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        base,
        commit,
        "--",
        *CHANGED_PATHS,
    )  # the prefixes named, so a person's diff.noprefix or mnemonicPrefix never empties the changed text
    cur: str | None = None
    for line in diff.split("\n"):
        if line.startswith("+++ "):
            name = line[4:]
            cur = name[2:] if name.startswith("b/") else None
            continue
        m = re.match(r"@@ -\S+ \+(\d+)(?:,(\d+))? @@", line)
        if m and cur:
            start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
            out.setdefault(cur, set()).update(range(start, start + count))
    return {k: v for k, v in out.items() if v}


def changed_ledger_entries(top: Path, base: str, commit: str) -> list[str]:
    names = git(top, "diff", "--name-only", "--no-renames", "--diff-filter=d", base, commit, "--", "docs/ledger")
    return [n for n in names.split() if re.search(r"(^|/)TD-\d+\.md$", n)]


def rule_files(tree: Path, ledger_entries: list[str]) -> list[str]:
    rels: list[str] = []
    for d in RULE_DIRS:
        root = tree / d
        if root.is_dir():
            for dirpath, _dirs, files in os.walk(root):
                for f in files:
                    rels.append(Path(dirpath, f).relative_to(tree).as_posix())
    if (tree / GLOSSARY).is_file():
        rels.append(GLOSSARY)
    rels.extend(ledger_entries)
    return sorted(set(rels))


def entry_file(tree: Path, td: str) -> str | None:
    for rel in (f"docs/ledger/{td}.md", f"docs/ledger/archive/{td}.md"):
        if (tree / rel).is_file():
            return rel
    return None


def entry_field(text: str, name: str) -> str:
    """A ledger entry's `**<name>:**` body, to the next field or heading."""
    out: list[str] = []
    inside = False
    for line in text.split("\n"):
        if FIELD_RE.match(line) or line.startswith("#"):
            inside = line.startswith(f"**{name}:**")
            if inside:
                out.append(line[len(name) + 5 :])
            continue
        if inside:
            out.append(line)
    return collapse("\n".join(out))


def cadence_root(tree: Path) -> Path | None:
    """The pinned agent-cadence tree the commit names, or None when it cannot be found."""
    try:
        r = subprocess.run(
            ["agent-cadence", "-C", str(tree), "path", "scripts/ledger.py"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = r.stdout.strip().splitlines()
    if r.returncode != 0 or not out:
        return None
    return Path(out[-1]).parents[1]


# --- the four checks ------------------------------------------------------------------------------------------------


def term_in(term: str, text: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(collapse(term)) + r"(?!\w)", text, re.IGNORECASE) is not None


def check_rules(prep: Prep, paras: list[Para]) -> list[Flag]:
    flags: list[Flag] = []
    for r in prep.rules:
        rx = re.compile(r["find"])
        hits = [p for p in paras if rx.search(p.text)]
        if len(hits) < 2:
            flags.append(
                Flag(
                    "rules",
                    prep.path,
                    prep.line_of(r["name"]),
                    collapse(r["name"]),
                    f"{r['name']}: declared but not repeated ({len(hits)} paragraph(s) match its find)",
                )
            )
        for p in hits:
            missing = [t for t in r["terms"] if not term_in(t, p.text)]
            if missing:
                flags.append(
                    Flag(
                        "rules",
                        p.file,
                        p.line,
                        p.text,
                        f"{r['name']}: missing {', '.join(missing)} · {p.text}",
                        rule=r["name"],
                    )
                )
    return flags


def glob_count(tree: Path, spec: dict) -> int:
    files = sorted(f for f in glob.glob(spec["glob"], root_dir=tree, recursive=True) if (tree / f).is_file())
    rx = re.compile(spec["grep"]) if spec.get("grep") is not None else None
    if not spec.get("lines"):
        if rx is None:
            return len(files)
        return sum(1 for f in files if _any_line(rx, read(tree, f)))
    n = 0
    for f in files:
        text = read(tree, f)
        if text is None:
            continue
        n += sum(1 for line in text.splitlines() if rx is None or rx.search(line))
    return n


def _any_line(rx: re.Pattern, text: str | None) -> bool:
    return bool(text) and any(rx.search(line) for line in text.splitlines())


def check_claims(
    prep: Prep, tree: Path, ac_root: Path | None, changed: list[Para], added: dict[str, set[int]], cnr: list[str]
) -> list[Flag]:
    flags: list[Flag] = []

    def flag(claim: dict, why: str) -> None:
        flags.append(
            Flag("claims", prep.path, prep.line_of(claim["says"]), collapse(claim["says"]), f"{claim['says']}: {why}")
        )

    for c in prep.claims:
        if "at" in c:
            m = re.fullmatch(r"(.+?)(?::(\d+))?", c["at"])
            path, line = m.group(1), m.group(2)
            if path.startswith("agent-cadence:"):
                if ac_root is None:
                    cnr.append(f"agent-cadence path: the pinned tree could not be found for {c['at']}")
                    continue
                base, rel = ac_root, path[len("agent-cadence:") :]
            else:
                base, rel = tree, path
            target = base / rel
            if not target.is_file():
                flag(c, f"{path} does not exist at the commit")
                continue
            try:
                text = target.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                flag(c, f"{path} is not a text file")
                continue
            lines = text.splitlines()
            if line is not None and not 1 <= int(line) <= len(lines):
                flag(c, f"{path} has {len(lines)} lines, not line {line}")
            if "has" in c and not any(c["has"] in ln for ln in lines):
                flag(c, f"{path} does not hold {c['has']!r}")
        else:
            got = glob_count(tree, c["count"])
            if got != c["is"]:
                flag(c, f"count of {c['count']['glob']} is {got}, not {c['is']}")
    new_paths = {posixpath.normpath(n["path"]) for n in prep.new}
    for n in prep.new:
        rel = posixpath.normpath(n["path"])
        if (tree / rel).exists():
            flags.append(
                Flag(
                    "claims",
                    prep.path,
                    prep.line_of(n["path"]),
                    n["path"],
                    f"{n['path']}: a new path that exists now; drop the item",
                )
            )
            continue
        ef = entry_file(tree, n["by"])
        if ef is None:
            why = f"{n['by']} is not in the ledger"
        elif n["path"] not in entry_field(read(tree, ef) or "", "Fix"):
            why = f"{n['by']}'s Fix does not name it"
        else:
            continue
        flags.append(Flag("claims", prep.path, prep.line_of(n["path"]), n["path"], f"{n['path']}: {why}"))
    for p in changed:
        for rel, line in paths_in(p, added):
            if rel in new_paths or (tree / rel).exists() or (ac_root is not None and (ac_root / rel).exists()):
                continue
            if ac_root is None:
                cnr.append(f"agent-cadence path: the pinned tree could not be found to read {rel}")
                continue
            flags.append(Flag("claims", p.file, line, rel, f"{rel} does not exist at the commit"))
    return flags


def paths_in(p: Para, added: dict[str, set[int]]) -> list[tuple[str, int]]:
    """Each repo path written in the paragraph on an added line, resolved: (repo-relative path, line)."""
    out: list[tuple[str, int]] = []
    adds = added.get(p.file, set())
    for tok in re.finditer(r"\S+", p.text):
        t = tok.group(0)
        bare = t.strip("*_`.,;:()")  # emphasis around a path is not a glob
        if any(c in bare for c in "<*$") or "://" in t or t.lower().startswith("www."):
            continue
        links = [m.span(1) for m in LINK_TARGET_RE.finditer(t)]
        for run in PATH_RUN_RE.finditer(t):
            s = run.group(0).rstrip(".")
            if not s or "/" not in s or s.startswith("/") or not EXT_RE.search(s):
                continue
            if run.start() > 0 and t[run.start() - 1] == "~":
                continue
            line = p.line_at(tok.start() + run.start())
            if line not in adds:
                continue
            if any(a <= run.start() and run.end() <= b for a, b in links):
                rel = posixpath.normpath(posixpath.join(posixpath.dirname(p.file), s))
            else:
                rel = posixpath.normpath(s)
            out.append((rel, line))
    return out


def norm_title(s: str) -> str:
    return collapse(s).strip().rstrip(".,;:!?").strip().lower()


def section_titles(text: str) -> set[str]:
    leads = [m.group(1) for m in BOLD_RE.finditer(collapse(text))] + HEADING_RE.findall(text)
    out: set[str] = set()
    for lead in leads:
        out.add(norm_title(lead))
        out.add(norm_title(lead.split(":")[0]))
        out.add(norm_title(lead.split("(")[0]))
    out.discard("")
    return out


def design_index(tree: Path) -> dict[str, str]:
    text = read(tree, "docs/design.md") or ""
    return {m.group(1): posixpath.normpath(posixpath.join("docs", m.group(2))) for m in INDEX_RE.finditer(text)}


def _skips(word_before: str) -> bool:
    w = word_before.strip("([`*_\"'")
    w = re.sub(r"(?:'|’)s$", "", w)
    if w.lower() in SKIP_WORDS:
        return True
    if "](" in w or w.endswith("]"):
        return True  # a link
    return bool(re.search(r"[\w-]\.[A-Za-z][A-Za-z0-9]{0,7}$", w))  # a file name


def check_pointers(tree: Path, changed: list[Para], added: dict[str, set[int]]) -> list[Flag]:
    flags: list[Flag] = []
    index = design_index(tree)
    titles: dict[str, set[str]] = {}
    for p in changed:
        adds = added.get(p.file, set())
        prev_end, prev_skip = -1, False
        for m in SECTION_RE.finditer(p.text):
            gap = p.text[prev_end : m.start()] if prev_end >= 0 else None
            if gap is not None and LIST_GAP_RE.fullmatch(gap):
                skip = prev_skip
            else:
                before = p.text[: m.start()].rstrip()
                wb = re.search(r"(\S+)$", before)
                skip = bool(wb) and _skips(wb.group(1))
            t = TITLE_AFTER_RE.match(p.text, m.end())
            prev_end, prev_skip = (t.end() if t else m.end()), skip
            line = p.line_at(m.start())
            if skip or line not in adds:
                continue
            num = m.group(1)
            written = p.text[m.start() : t.end()] if t else m.group(0)
            if num not in index:
                flags.append(
                    Flag("pointers", p.file, line, written, f"{written}: §{num} is not in docs/design.md's index")
                )
                continue
            if t:
                f = index[num]
                if f not in titles:
                    titles[f] = section_titles(read(tree, f) or "")
                if norm_title(t.group(1)) not in titles[f]:
                    flags.append(
                        Flag(
                            "pointers",
                            p.file,
                            line,
                            written,
                            f"{written}: no lead or heading of {f} reads {t.group(1)!r}",
                        )
                    )
        for m in TD_RE.finditer(p.text):
            line = p.line_at(m.start())
            if line in adds and entry_file(tree, m.group(0)) is None:
                flags.append(
                    Flag(
                        "pointers",
                        p.file,
                        line,
                        m.group(0),
                        f"{m.group(0)} is not in the ledger, its archive, or the PR",
                    )
                )
    return flags


def _def_line(tree: Path, rel: str, test: str) -> int:
    name = test.split("[")[0].split("::")[-1]
    for i, line in enumerate((read(tree, rel) or "").split("\n"), 1):
        if re.match(rf"\s*(?:async\s+)?def {re.escape(name)}\(", line):
            return i
    return 1


def run_tools(tree: Path, base: str) -> tuple[list[Flag], list[str]]:
    """The ledger check and the doc-bound tests at the commit: their flags, and each tool that could not run."""
    flags: list[Flag] = []
    cnr: list[str] = []
    try:
        r = subprocess.run(
            ["agent-cadence", "run", "ledger.py", "--check", "--json", "--since", base],
            cwd=tree,
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT,
            check=False,
        )
        data = json.loads(r.stdout)
        for f in data.get("flags", []):
            if f.get("level") != "error" or f.get("standing"):
                continue
            rel = entry_file(tree, f["id"]) if f.get("id") else None
            flags.append(
                Flag("tools", rel or "docs/ledger", 1, collapse(f.get("text", "")), collapse(f.get("text", "")))
            )
    except OSError:
        cnr.append("ledger check: agent-cadence will not start")
    except subprocess.TimeoutExpired:
        cnr.append(f"ledger check: timed out after {TOOL_TIMEOUT} s")
    except (ValueError, AttributeError, KeyError, TypeError) as e:
        cnr.append(f"ledger check: unreadable output ({type(e).__name__})")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(tree / "src")] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *DOC_TESTS, "-q", "-rf", "-p", "no:cacheprovider"],
            cwd=tree,
            env=env,
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT,
            check=False,
        )
        if r.returncode == 1:
            failed = re.findall(r"^FAILED (\S+?)::(.+?)(?: - .*)?$", r.stdout, re.MULTILINE)
            if not failed:
                last = (r.stderr.strip() or r.stdout.strip()).split("\n")[-1]
                cnr.append(f"doc-bound tests: exit 1 with no failed test named ({collapse(last)[:160]})")
            for rel, test in failed:
                flags.append(Flag("tools", rel, _def_line(tree, rel, test), test, f"{test} failed"))
        elif r.returncode != 0:
            cnr.append(f"doc-bound tests: pytest exit {r.returncode}")
    except OSError:
        cnr.append("doc-bound tests: pytest will not start")
    except subprocess.TimeoutExpired:
        cnr.append(f"doc-bound tests: timed out after {TOOL_TIMEOUT} s")
    return flags, cnr


def apply_waivers(prep: Prep, flags: list[Flag]) -> tuple[list[Flag], int]:
    hidden: set[int] = set()
    left: list[Flag] = []
    for w in prep.waive:
        text = collapse(w["text"])
        used = False
        for i, f in enumerate(flags):
            if not f.hideable or f.check != w["check"] or f.file != w["file"]:
                continue
            if f.rule is not None:
                ok = w.get("rule") == f.rule and f.text.startswith(text)
            else:
                ok = collapse(f.text) == text and w.get("rule") in (None, f.text)
            if ok:
                hidden.add(i)
                used = True
        if not used:
            left.append(
                Flag(
                    "waive",
                    prep.path,
                    prep.line_of(w["text"]),
                    text,
                    f"a waiver that hides no flag: {w['check']} · {w['file']} · {text}",
                    hideable=False,
                )
            )
    return [f for i, f in enumerate(flags) if i not in hidden] + left, len(hidden)


# --- the run --------------------------------------------------------------------------------------------------------


def prune_stale(top: Path) -> None:
    """Remove each of our own worktrees whose directory is gone — never a bare `git worktree prune`."""
    for line in git(top, "worktree", "list", "--porcelain").split("\n"):
        if line.startswith("worktree "):
            path = line[len("worktree ") :]
            if Path(path).name.startswith(PREFIX) and not Path(path).exists():
                git(top, "worktree", "remove", "--force", path, check=False)


def dirty(top: Path, prep_rel: str) -> list[str]:
    out = git(top, "status", "--porcelain", "--untracked-files=all", "--", *CHANGED_PATHS, prep_rel)
    return [ln[3:] for ln in out.split("\n") if ln.strip()]


def check(entry: str, rev: str, base: str | None) -> tuple[int, list[str]]:
    if not re.fullmatch(r"TD-\d+", entry):
        raise NotPrepared(f"--entry {entry!r} is not TD-<n>")
    prep_rel = f"docs/reviews/{entry}.prep.yml"
    top = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    prune_stale(top)  # every run first, whatever it ends in
    if rev == "HEAD":
        d = dirty(top, prep_rel)
        if d:
            raise NotPrepared(f"uncommitted or untracked changes: {', '.join(d[:5])}{' …' if len(d) > 5 else ''}")
    commit = git(top, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}", check=False).strip()
    if not commit:
        raise CannotRun(f"cannot resolve --rev {rev}")
    if base:
        b = git(top, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}", check=False).strip()
        if not b:
            raise CannotRun(f"cannot resolve --base {base}")
    else:
        b = git(top, "merge-base", commit, "origin/main", check=False).strip()
        if not b:
            raise CannotRun("no merge base with origin/main (fetch it, or pass --base)")
    tree = Path(tempfile.mkdtemp(prefix=PREFIX))
    try:
        git(top, "worktree", "add", "--detach", "--quiet", str(tree), commit)
        return _check_tree(entry, prep_rel, top, tree, commit, b)
    finally:
        git(top, "worktree", "remove", "--force", str(tree), check=False)
        shutil.rmtree(tree, ignore_errors=True)


def _check_tree(entry: str, prep_rel: str, top: Path, tree: Path, commit: str, base: str) -> tuple[int, list[str]]:
    raw = read(tree, prep_rel)
    if raw is None:
        raise NotPrepared(f"no {prep_rel} at {commit[:12]}")
    prep = load_prep(prep_rel, raw)
    added = added_lines(top, base, commit)
    ledger_entries = changed_ledger_entries(top, base, commit)
    paras_by_file: dict[str, list[Para]] = {}
    for rel in rule_files(tree, ledger_entries):
        text = read(tree, rel)
        if text is not None:
            paras_by_file[rel] = paragraphs(rel, text, ledger=is_ledger(rel))
    check_waiver_floor(prep, paras_by_file)
    changed: list[Para] = []
    for rel in sorted(added):
        text = read(tree, rel)
        if text is not None:
            changed.extend(
                p for p in paragraphs(rel, text, ledger=is_ledger(rel)) if any(n in added[rel] for n in p.lines)
            )
    cnr: list[str] = []
    flags = check_rules(prep, [p for ps in paras_by_file.values() for p in ps])
    flags += check_claims(prep, tree, cadence_root(tree), changed, added, cnr)
    flags += check_pointers(tree, changed, added)
    tflags, tcnr = run_tools(tree, base)
    flags += tflags
    cnr += tcnr
    flags, waived = apply_waivers(prep, flags)
    head = f"{entry} · {commit[:12]} · base {base[:12]}"
    if flags:
        lines = [f"design-prep: FAIL · {head} · flags {len(flags)}"]
        lines += [f.render() for f in flags]
        lines += [f"tools · could not run · {c}" for c in cnr]
        return 1, lines
    if cnr:
        return 3, [f"design-prep: CANNOT RUN · {head} · {'; '.join(cnr)}"]
    return 0, [
        f"design-prep: PASS · {head} · claims {len(prep.claims)} · rules {len(prep.rules)} · "
        f"new {len(prep.new)} · waived {waived}"
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--entry", required=True, help="the design entry, TD-<n>")
    ap.add_argument("--rev", default="HEAD", help="the commit to check (default HEAD)")
    ap.add_argument("--base", help="the base the changed text is read against (default: merge base with origin/main)")
    ap.add_argument("--advisory", action="store_true", help="print the same lines under ADVISORY and exit 0")
    args = ap.parse_args(argv)
    try:
        code, lines = check(args.entry, args.rev, args.base)
    except NotPrepared as e:
        code, lines = 2, [f"design-prep: NOT PREPARED · {e}"]
    except CannotRun as e:
        code, lines = 3, [f"design-prep: CANNOT RUN · {e}"]
    except Exception as e:  # the script's own crash is a CANNOT RUN, never a traceback first
        code, lines = 3, [f"design-prep: CANNOT RUN · crash: {type(e).__name__}: {collapse(e)}"]
    if args.advisory:
        lines[0] = "design-prep: ADVISORY · " + lines[0][len("design-prep: ") :]
        code = 0
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
