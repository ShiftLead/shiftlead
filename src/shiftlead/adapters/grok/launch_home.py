"""The launch home and the `all` refusal's read of Claude Code's files (design §4.3 *The third adapter: Grok Build*,
*`launch`*, TD-1836).

Grok Build reads Claude Code's settings files for its permission mode, and a `defaultMode` it reads there wins over the
launch's `--permission-mode` (TD-1835's probes, 1.0.77). So every launch runs with `HOME` the launch home,
`<config_dir>/launch-home/`: the person's home by symbolic links, but `.grok`, and `.claude`, a directory of its own
whose entries are links in turn, but `settings.json` and `settings.local.json`. `refresh` makes or refreshes it.

An unattended launch under `permission_prompts: all` reads the `defaultMode` of the files the tool still reads (the
managed file and a project's) and refuses the launch on one that would break §4.2a's promise: `all_refusal`.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import time
from pathlib import Path

LAUNCH_HOME = "launch-home"  # under the profile's config_dir
SETTINGS = ("settings.json", "settings.local.json")  # Claude Code's two user-level settings files, never mirrored
NOT_LINKED = (".grok", ".claude")  # the person's own Grok home, never linked; `.claude`, a directory of its own
TMP = ".shiftlead-tmp-"
MODES = ("default", "acceptEdits", "auto", "dontAsk", "bypassPermissions", "plan")  # Claude Code's six
ATTEMPTS = 8  # a link's re-reads after a concurrent refresh moved its name (EEXIST, a rename's ENOENT)


def path_for(config_dir: Path) -> Path:
    return config_dir / LAUNCH_HOME


def refresh(home: Path, launch_home: Path) -> Path:
    """Make or refresh `launch_home` as the mirror of `home` (§4.3 *`launch`*'s refresh): a link per name the home
    holds in any form (a dangling link too) but `.grok` and `.claude`, its target `<home>/<name>` as written; a link
    pointing elsewhere replaced; a non-link under a home's name moved aside as a shadow; a link whose name the home
    no longer holds removed; any other non-link, and a `.grok` of either kind, left. `.claude` is always a directory
    holding the same mirror of `<home>/.claude`, but the two settings files, a link under either name removed and a
    non-link moved aside. An `OSError` is the caller's to refuse the launch with."""
    home = Path(os.path.abspath(home))
    launch_home.mkdir(parents=True, exist_ok=True)
    _mirror(home, launch_home, set(os.listdir(home)) - set(NOT_LINKED), keep=NOT_LINKED)
    claude = launch_home / ".claude"
    if os.path.islink(claude):
        _unlink(claude)
    elif os.path.lexists(claude) and not claude.is_dir():
        _aside(launch_home, ".claude", "shadow")
    claude.mkdir(exist_ok=True)
    try:
        names = set(os.listdir(home / ".claude"))  # through it where it is a link to a directory
    except (FileNotFoundError, NotADirectoryError):
        names = set()  # absent, a file, or a dangling link: nothing to mirror
    for name in SETTINGS:
        p = claude / name
        if os.path.islink(p):
            _unlink(p)
        elif os.path.lexists(p):
            _aside(claude, name, "removed")
    _mirror(home / ".claude", claude, names - set(SETTINGS), keep=())
    return launch_home


def _mirror(src: Path, dst: Path, names: set[str], *, keep: tuple[str, ...]) -> None:
    for name in sorted(names):
        _place(dst, name, os.path.join(src, name))
    for name in os.listdir(dst):
        if name not in names and name not in keep and os.path.islink(dst / name):
            _unlink(dst / name)  # a name the home no longer holds, or a temporary link a crash left


def _place(dst: Path, name: str, target: str) -> None:
    """`dst/name` a link to `target`, made under a temporary name and renamed into place; after an `EEXIST` or a
    rename's `ENOENT` (a concurrent refresh) the name is read again and the link made where still missing or wrong."""
    p = dst / name
    for _ in range(ATTEMPTS):
        try:
            if os.readlink(p) == target:
                return
        except FileNotFoundError:
            pass
        except OSError as e:
            if e.errno != errno.EINVAL:
                raise
            _aside(dst, name, "shadow")  # a non-link under the home's name: a frozen copy is never read
        tmp = dst / f"{TMP}{os.getpid()}-{name}"
        try:
            if os.path.lexists(tmp):
                _unlink(tmp)  # one found existing: removed and made again
            os.symlink(target, tmp)
            os.rename(tmp, p)
        except FileExistsError:
            continue
        except FileNotFoundError:
            continue  # the temporary link removed under us by a concurrent refresh
        return
    raise OSError(errno.EAGAIN, f"{p} kept changing under the refresh")


def _aside(dst: Path, name: str, kind: str) -> None:
    """Move `dst/name` to `<name>.shiftlead-<kind>-<stamp>`, `-<n>` appended while the name is taken; gone already
    (a concurrent refresh moved it) is no error."""
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    base = f"{name}.shiftlead-{kind}-{stamp}"
    to, n = base, 1
    while os.path.lexists(dst / to):
        to, n = f"{base}-{n}", n + 1
    with contextlib.suppress(FileNotFoundError):
        os.rename(dst / name, dst / to)


def _unlink(p: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.unlink(p)


# -- the `all` refusal (§4.3: what crosses with no switch) ----------------------------------------


def files_read(cwd: Path, managed: Path) -> list[Path]:
    """The Claude Code files the tool reads for a session in `cwd` once the home's are out of reach, in the order the
    launch reads them: the managed file, then `.claude/settings.local.json` and `settings.json` in `cwd` and each
    ancestor up to the nearest one holding a `.git` entry (file or directory), or `cwd` alone where none does."""
    start = Path(os.path.abspath(cwd))
    dirs, d = [], start
    while True:
        dirs.append(d)
        if os.path.lexists(d / ".git"):
            break
        if d.parent == d:
            dirs = [start]  # no repo: the session's directory alone
            break
        d = d.parent
    return [managed, *(d / ".claude" / n for d in dirs for n in reversed(SETTINGS))]


def file_refusal(path: Path, profile: str, *, env_keys: tuple[str, ...] = ()) -> str | None:
    """The refusal one file earns under `permission_prompts: all`, in §4.3's words, or None: a mode other than
    `default` among the six, nested or top-level; a file that cannot be read or parsed, or a mode that is not a string
    or not one of the six. A missing file, or no mode, is none. `env_keys` names the prefixes and names an `env` entry
    refuses on (read after the mode); empty, `env` is not read."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return cannot_read(path, e, profile)
    if not isinstance(doc, dict):
        return cannot_read(path, "not a JSON object", profile)
    perms = doc.get("permissions", {})
    if not isinstance(perms, dict):
        return cannot_read(path, "permissions is not an object", profile)
    for where, holder in (("permissions.defaultMode", perms), ("defaultMode", doc)):
        if "defaultMode" not in holder:
            continue
        mode = holder["defaultMode"]
        if not isinstance(mode, str) or mode not in MODES:
            return cannot_read(path, f"{where} {json.dumps(mode)} is not one of {', '.join(MODES)}", profile)
        if mode != "default":
            return would_run(path, f"defaultMode {mode}", profile)
    if env_keys and "env" in doc:
        env = doc["env"]
        if not isinstance(env, dict):
            return cannot_read(path, "env is not an object", profile)
        for key in env:
            if key in env_keys or any(key.startswith(p) for p in env_keys if p.endswith("_")):
                return would_run(path, f"env {key}", profile)
    return None


def all_refusal(cwd: Path, managed: Path, profile: str, *, env_keys: tuple[str, ...] = ()) -> str | None:
    """The first offender among `files_read(cwd, managed)`, or None."""
    for path in files_read(cwd, managed):
        if why := file_refusal(path, profile, env_keys=env_keys):
            return why
    return None


def would_run(path: Path, what: str, profile: str) -> str:
    return (
        f"Grok would run {profile} under {path}'s {what}, not asking as permission_prompts: all says; "
        "use another profile or remove the mode"
    )


def cannot_read(path: Path, error: object, profile: str) -> str:
    return (
        f"Grok's permission mode under {path} cannot be read ({error}), "
        f"so {profile} cannot keep permission_prompts: all"
    )


def home_settings(home: Path) -> list[tuple[Path, dict]]:
    """The person's `~/.claude/settings.json` and `settings.local.json` that parse as objects, for `ao doctor`'s
    notes; one missing or unreadable is skipped (the launch never reads them)."""
    out = []
    for name in SETTINGS:
        p = home / ".claude" / name
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if isinstance(doc, dict):
            out.append((p, doc))
    return out
