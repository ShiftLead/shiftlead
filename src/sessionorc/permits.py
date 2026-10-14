"""What always reaches the person, whatever a rule or the director seat says (design §4.9b *What
always reaches the person*, TD-641): a permission prompt that names `~/.shiftlead`, `~/.claude`, a
systemd unit, or a path outside the member's own worktree and its repo's checkout. The host agent
refuses an *allow* of such a prompt — a rule's here, the director's `permit` (TD-642) through the
same function — while a *deny* stands.

Tool-agnostic: it reads the strings a prompt touches — the adapter's `prompt_strings(tool, input)`
says which (its command lines and paths, never a file's content), and with no such method every
string of the input is read — as shell words, never by a tool's name. Conservative on purpose: a
word it cannot place (a variable in a path, a `cd` it cannot follow) is the person's. A quoted
command is read as one (`bash -c '…'`); code an interpreter runs (`python -c`, `node -e`) is not,
so a rule allowing one is the person's own risk.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Any

from sessionorc import paths

# what a word carries before its path: a redirection (`2>`, `>>`, `<`), a short flag glued to it
# (`-o/x`), an option's `=`, a `file://` scheme
_REDIRECT = re.compile(r"^[0-9]*(?:[<>]+|&>>?)&?")
_GLUED = re.compile(r"^-[A-Za-z]+(?=[/~.$])")
_HOME_VAR = re.compile(r"\$\{?HOME\}?(?![\w])")
_UNIT = re.compile(r"\.(service|timer|socket|target|mount|path|slice)$")
_SYSTEMD_WORDS = {"systemctl", "journalctl", "loginctl", "systemd-run"}
_JOINERS = {"&&", "||", ";", "|", "&", "(", ")", "{", "}"}
_ASSIGNED = re.compile(r"^[\w.-]+=")  # `VAR=/x`, `if=/x`: the value is a word of its own
# a stream, never a file anyone touches: writing to one is not a path outside the worktree
_HARMLESS = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"}
_WALK_CAP = 200  # strings read from one input; a prompt is a command line or a few fields


def all_strings(value: Any, out: list[str] | None = None) -> list[str]:
    """Every string in a prompt's input, for an adapter that does not say which are its paths."""
    out = [] if out is None else out
    if len(out) >= _WALK_CAP:
        return out
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            all_strings(v, out)
    elif isinstance(value, list | tuple):
        for v in value:
            all_strings(v, out)
    return out


def _words(text: str) -> list[str]:
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars=";&|()<>")
        lex.whitespace_split = True
        return list(lex)
    except ValueError:  # an unbalanced quote: split on blanks, which can only find more paths
        return text.split()


def _within(p: Path, roots: list[Path]) -> bool:
    return any(p == r or r in p.parents for r in roots)


class _Place:
    def __init__(self, dir: str, repo: str | None) -> None:
        self.home = Path(os.path.expanduser("~"))
        self.held = [self.home / ".shiftlead", self.home / ".claude", Path(os.path.realpath(paths.home()))]
        self.own = Path(os.path.realpath(dir)) if dir else None
        self.repo = Path(os.path.realpath(repo)) if repo else None
        self.roots = [r for r in (self.own, self.repo) if r is not None]

    def why(self, p: Path, word: str) -> str | None:
        if _within(p, self.held):
            return f"it names {word}, the home's own"
        if not _within(p, self.roots):
            return f"it names {word}, outside the member's worktree and checkout"
        if "systemd" in p.parts:
            return f"it names {word}, a systemd unit"
        mine = self.own is not None and _within(p, [self.own])
        for root in self.roots:
            if not _within(p, [root]):
                continue
            rel = p.relative_to(root).parts
            if rel[:1] == (".git",):
                return f"it names {word}, the repo's own git directory"
            if rel[:2] == (".claude", "worktrees") and not mine:
                return f"it names {word}, another member's worktree"
            if rel[:1] == (".claude",) and len(rel) >= 2 and (rel[1].startswith("settings") or rel[1] == "hooks"):
                return f"it names {word}, the tool's own settings or hooks"
        return None


def always_the_person(strings: list[str], dir: str, repo: str | None) -> str | None:
    """Why a prompt whose command lines and paths are `strings` is the person's alone, or None. `dir`
    is the member's worktree (its record's `dir`), `repo` its repo's checkout."""
    place = _Place(dir, repo)
    try:
        for text in strings[:_WALK_CAP]:
            if why := _one(text, place):
                return why
    except (ValueError, OSError) as e:  # a NUL in a path, a loop of links: nothing to place it by
        return f"it names a path that cannot be read ({e})"
    return None


def _one(text: str, place: _Place) -> str | None:
    cwd = place.own or Path("/")
    after_cd = False
    for raw in _words(_HOME_VAR.sub("~", text)):
        if raw in _JOINERS:
            if after_cd:
                return "it changes directory to home"
            continue
        if raw and set(raw) <= set("<>&"):
            continue  # a redirection on its own: the next word is its target
        if any(c.isspace() for c in raw) and (why := _one(raw, place)):
            return why  # a quoted command (`bash -c '…'`, `eval '…'`) is read as one
        word = raw
        if _ASSIGNED.match(word):
            word = word.split("=", 1)[1]
        if word in _SYSTEMD_WORDS or _UNIT.search(word):
            return "it names a systemd unit"
        word = _REDIRECT.sub("", word)
        word = _GLUED.sub("", word)
        if word.startswith("--") and "=" in word:
            word = word.split("=", 1)[1]
        if word.startswith("file://"):
            word = word[len("file://") :] or "/"
        if after_cd:
            after_cd = False
            if word in ("", "-") or "$" in word or "`" in word:
                return f"it changes directory to {raw or 'home'}, which cannot be followed"
            cwd = Path(os.path.realpath(cwd / os.path.expanduser(word)))
            if why := place.why(cwd, raw):
                return why
            continue
        if raw == "cd":
            after_cd = True
            continue
        if not word or word in _HARMLESS:
            continue
        if word.startswith("~"):
            if word != "~" and not word.startswith("~/"):
                return f"it names {raw}, another account's home"
            p = Path(os.path.realpath(os.path.expanduser(word)))
        elif "$" in word and ("/" in word or word.startswith("$")) and re.search(r"\$\{?[A-Za-z_]", word):
            if "/" in word:
                return f"it names {raw}, a path through a variable"
            continue
        elif word.startswith("/"):
            p = Path(os.path.realpath(word))
        elif ".." in word.split("/") or word.startswith("./") or "/" in word:
            p = Path(os.path.realpath(cwd / word))
        else:
            continue
        if why := place.why(p, raw):
            return why
    if after_cd:
        return "it changes directory to home"
    return None
