"""`ao migrate`: the one-time move from agentorc's machine names to shiftlead's (TD-060 step 2).

The project was `agentorc` until 2026-10-10. The rename is a clean cut: the code reads only the new
names, and this moves what one machine holds under the old ones, once, with no session running —
a session started before it holds `AGENTORC_SESSION` and resolves the old hook, so a move under a
live session breaks its hooks. In order:

1. refused while the tmux server holds any session, while the old home is absent, and while the
   new one already exists;
2. the old user units (`agentorc-agent`, `agentorc-ui`) stopped, disabled and removed;
3. `~/.agentorc` renamed to `~/.shiftlead` (its git history of the definition files goes with it);
4. the old names rewritten in its small text files (the YAML and JSON at its top, the launch
   records, each node's `hosts.yml`/`profiles.yml`), and the generated Claude Code hook files
   removed — every launch writes its own again;
5. each container node's venv removed: its scripts name `/agentorc/venv`, and the node's volume is
   mounted at `/shiftlead` now; `ao host up` installs it again, and the node's logins are kept.

What is left is printed, not done: `ao service install` from the new venv (the user units), and
the root line that swaps the two system units (`install --system` removes the old ones). A repo's
`.agentorc.yml` is read as a fallback until that repo renames it (`sessionorc.paths.repo_file`).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

OLD_HOME = Path("~/.agentorc")
OLD_UNITS = ("agentorc-agent", "agentorc-ui")
# The old names as they appear inside the home's own files: paths into it, the venv, the hook and
# the agent's console scripts, and the environment variables.
REWRITES = (
    ("/.agentorc", "/.shiftlead"),
    ("agentorc-venv", "shiftlead-venv"),
    ("agentorc-hook", "shiftlead-hook"),
    ("agentorc-agent", "shiftlead-agent"),
    ("AGENTORC_", "SHIFTLEAD_"),
)
TEXT_GLOBS = ("*.yml", "*.yaml", "*.json", "launch/*.json", "nodes/*/home/*.yml")


def live_sessions() -> list[str]:
    """The sessions the person's default tmux server holds now; none when no server answers."""
    try:
        cp = subprocess.run(["tmux", "list-sessions", "-F", "#{session_name}"], capture_output=True, text=True)
    except FileNotFoundError:
        return []
    return [s for s in cp.stdout.split() if s] if cp.returncode == 0 else []


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


def run(
    *,
    old: Path | None = None,
    new: Path | None = None,
    unit_dir: Path | None = None,
    sessions: Callable[[], list[str]] = live_sessions,
    systemctl: Callable[..., subprocess.CompletedProcess[str]] = _systemctl,
) -> list[str]:
    """Do the move; return what was done, one line each. Raises RuntimeError, saying why, when refused."""
    from sessionorc import paths
    from shiftlead import service

    old = (old or OLD_HOME).expanduser()
    new = (new or paths.home()).expanduser()
    unit_dir = unit_dir or service.UNIT_DIR
    live = sessions()
    if live:
        raise RuntimeError(f"{len(live)} session(s) still run ({', '.join(live)}): close them first, then migrate")
    if not old.is_dir():
        raise RuntimeError(f"nothing to migrate: no {old}")
    if new.exists():
        raise RuntimeError(f"{new} already exists: move it aside or remove it, then migrate")
    done = []
    files = [unit_dir / f"{u}.service" for u in OLD_UNITS]
    if any(f.exists() for f in files):
        systemctl("disable", "--now", *[f.name for f in files if f.exists()])
        for f in files:
            f.unlink(missing_ok=True)
        systemctl("daemon-reload")
        done.append(f"stopped and removed {', '.join(OLD_UNITS)}")
    new.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(old), str(new))
    done.append(f"moved {old} to {new}")
    rewritten = []
    for pattern in TEXT_GLOBS:
        for f in sorted(new.glob(pattern)):
            if not f.is_file() or f.is_symlink():
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            out = text
            for a, b in REWRITES:
                out = out.replace(a, b)
            if out != text:
                f.write_text(out, encoding="utf-8")
                rewritten.append(str(f.relative_to(new)))
    if rewritten:
        done.append(f"rewrote the old names in {', '.join(rewritten)}")
    # a container node's venv carries `/agentorc/venv` in its scripts' shebangs: `ao host up` makes it again
    venvs = sorted(d for d in new.glob("nodes/*/venv") if d.is_dir() and not d.is_symlink())
    for d in venvs:
        shutil.rmtree(d)
    if venvs:
        done.append(
            f"removed {len(venvs)} node venv(s) ({', '.join(d.parent.name for d in venvs)}): "
            "`ao host up` installs them again"
        )
    hooks = sorted((new / "claude-hooks").glob("*.json"))
    for f in hooks:
        f.unlink()
    if hooks:
        done.append(f"removed {len(hooks)} generated hook file(s) under claude-hooks/ (each launch writes its own)")
    return done


def next_steps() -> list[str]:
    """What the person runs after the move, in order."""
    from shiftlead import service

    return [
        f"{service._bin('ao')} service install",
        service.system_line(),
    ]


def environment_warning() -> str | None:
    """A line when the shell still carries an old variable (a session started before the move)."""
    old = sorted(k for k in os.environ if k.startswith("AGENTORC_"))
    return f"this shell still carries {', '.join(old)}: open a new one" if old else None
