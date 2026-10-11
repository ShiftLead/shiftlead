"""`ao service install|uninstall|status`: systemd user units for the host agent and the UI
(design §4.1, §8 "a reboot must not need a human").

Two units, `shiftlead-agent` and `shiftlead-ui`, under `~/.config/systemd/user/`. `KillMode=process`
on the agent is load-bearing: tmux daemonises inside the service's cgroup, and the default
`control-group` kill mode would take the tmux server — and every session in it — down with any
agent restart or stop. With `process`, only the agent's own process is signalled; the tmux server
is deliberately left running when the unit stops.

A third unit, `shiftlead-tmux`, is a **system** unit (design §4.1, TD-488): the tmux server under
`system.slice`, outside the user manager's subtree, so a stop of `systemd --user` takes the agent
and the UI down and no session. It is root's to write: `install` stages its text under the home and
prints the one command the person runs as root, `ao service install --system`, which writes it in.

Beside it, the same press installs the **watch** (design §4.10 *When the home itself is down*, TD-497):
`shiftlead-watch.timer` runs `shiftlead-watch.service` every five minutes, a oneshot as the person whose
`ExecStartPre` (root's, by its `+`) starts the user manager when it is stopped; `shiftlead-watch` itself
(`shiftlead.watch`) asks the home's socket and tells the person.
"""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

UNIT_DIR = Path("~/.config/systemd/user").expanduser()
UNITS = ("shiftlead-agent", "shiftlead-ui")
TMUX_UNIT = "shiftlead-tmux"  # the system unit (design §4.1, TD-495)
WATCH_UNIT = "shiftlead-watch"  # the watch's service and timer, system units beside it (§4.10, TD-497)
SYSTEM_DIR = Path("/etc/systemd/system")
# The system units under the project's old name (TD-060): `install --system` stops and removes them
# before it writes the new ones, refused while their tmux server still holds a session.
LEGACY_SYSTEM_UNITS = ("agentorc-tmux.service", "agentorc-watch.timer", "agentorc-watch.service")
# Where the UI listens (design §4.5: localhost, never the LAN) — the one source `ao ui`, `shiftlead-ui`
# and `ao service install` default to (TD-149 (7)); the unit carries whatever the install was given.
DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8765


def _bin(name: str) -> str:
    """The console script next to this interpreter (pipx venv, pdm venv), else whatever PATH finds."""
    candidate = Path(sys.executable).parent / name
    if candidate.is_file():
        return str(candidate)
    return shutil.which(name) or name


def _path_env(home: str | None = None) -> str:
    """PATH for the units: the venv's bin (shiftlead-hook must resolve at launch), the user's
    ~/.local/bin (where `claude` usually lives), then the system defaults. `home` is the person's
    home directory where the caller is not the person (root, at `install --system`)."""
    parts = [
        str(Path(sys.executable).parent),
        str(Path(home) / ".local" / "bin") if home else str(Path("~/.local/bin").expanduser()),
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    return ":".join(dict.fromkeys(parts))


def unit_text(name: str, *, bind: str = DEFAULT_BIND, port: int = DEFAULT_PORT, home: str | None = None) -> str:
    env = [f"PATH={_path_env()}"]
    if home:
        env.append(f"SHIFTLEAD_HOME={home}")
    env_lines = "\n".join(f"Environment={e}" for e in env)
    if name == "shiftlead-agent":
        return f"""[Unit]
Description=shiftlead host agent (tmux sessions, hooks, run logs)

[Service]
Type=simple
ExecStart={_bin("shiftlead-agent")} serve
Restart=on-failure
RestartSec=2
KillMode=process
{env_lines}

[Install]
WantedBy=default.target
"""
    if name == "shiftlead-ui":
        return f"""[Unit]
Description=shiftlead web UI
After=shiftlead-agent.service
Wants=shiftlead-agent.service

[Service]
Type=simple
ExecStart={_bin("shiftlead-ui")} --bind {bind} --port {port}
Restart=on-failure
RestartSec=2
{env_lines}

[Install]
WantedBy=default.target
"""
    raise ValueError(name)


def tmux_unit_text(user: str, home: str | None = None) -> str:
    """The tmux server's system unit (design §4.1): `tmux -D` in the foreground on the default socket
    (`-D` is no daemon and turns `exit-empty` off), as the person, restarted always; its own stop is
    the one deliberate way to end every session at once (`KillMode=control-group`); `Delegate=yes`
    lets the host agent give each pane a cgroup of its own (§4.8a). No `XDG_RUNTIME_DIR` and no
    `DBUS_SESSION_BUS_ADDRESS`, so tmux opens no scope under the user manager. The tmux binary is
    the one the agent unit's PATH finds first, so client and server are one version; the text is
    the same made by the person or by root for them (`home`)."""
    path = _path_env(home)
    tmux = shutil.which("tmux", path=path) or "/usr/bin/tmux"
    return f"""[Unit]
Description=shiftlead tmux server (every session's panes, outside the user manager)

[Service]
Type=simple
User={user}
ExecStart={tmux} -D
Restart=always
RestartSec=2
KillMode=control-group
Delegate=yes
Environment=PATH={path}
Environment=LANG=C.UTF-8

[Install]
WantedBy=multi-user.target
"""


def watch_service_text(user: str, uid: int, home: str | None = None) -> str:
    """The watch's one run (design §4.10 *When the home itself is down*): a oneshot as the person;
    `ExecStartPre=+` runs as root and starts the user manager — a no-op while it runs — before
    `shiftlead-watch` asks the home's socket; its `-` lets a start that fails still be followed by the
    run, so a manager that will not start is told as silence rather than not at all. The same text
    made by the person or by root for them."""
    return f"""[Unit]
Description=shiftlead watch (the user manager runs; the host agent answers)

[Service]
Type=oneshot
User={user}
ExecStartPre=-+/usr/bin/systemctl start user@{uid}.service
ExecStart={_bin("shiftlead-watch")}
Environment=PATH={_path_env(home)}
Environment=LANG=C.UTF-8
"""


def watch_timer_text() -> str:
    """Every `WATCH_EVERY` (5 min), the first two minutes after boot (§4.10)."""
    return f"""[Unit]
Description=shiftlead watch, every five minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
Unit={WATCH_UNIT}.service

[Install]
WantedBy=timers.target
"""


def system_units(user: str, uid: int, home: str | None = None) -> dict[str, str]:
    """The system units' file names and texts, in the order they are enabled: the tmux server
    (design §4.1), then the watch's service and timer (§4.10)."""
    return {
        f"{TMUX_UNIT}.service": tmux_unit_text(user, home),
        f"{WATCH_UNIT}.service": watch_service_text(user, uid, home),
        f"{WATCH_UNIT}.timer": watch_timer_text(),
    }


def _staged() -> Path:
    from sessionorc import paths

    return paths.home() / "systemd"


def system_line() -> str:
    """The one command the person runs as root, by its absolute path: root's PATH has no venv."""
    return f"sudo {_bin('ao')} service install --system"


def stage_system_units(user: str | None = None) -> list[Path]:
    """`ao service install`'s third step (design §4.1, TD-495; the watch, TD-497): each system unit
    whose installed file is absent or differs from the text this install would write is written
    under the home for the person to read, and its path returned; none when every one is current."""
    staged = []
    for name, text in system_units(user or getpass.getuser(), os.getuid()).items():
        try:
            if (SYSTEM_DIR / name).read_text() == text:
                continue
        except OSError:
            pass
        path = _staged() / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        staged.append(path)
    return staged


def _server_answers(uid: int) -> bool:
    """Whether a tmux server listens on the person's default socket now."""
    import socket

    sock = Path(os.environ.get("TMUX_TMPDIR") or "/tmp") / f"tmux-{uid}" / "default"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(2)
        try:
            s.connect(str(sock))
        except OSError:
            return False
    return True


def _server_sessions(uid: int) -> list[str] | None:
    """The sessions on the person's default socket; [] when no server answers, None when it cannot be asked."""
    sock = Path(os.environ.get("TMUX_TMPDIR") or "/tmp") / f"tmux-{uid}" / "default"
    if not _server_answers(uid):
        return []
    cp = subprocess.run(
        ["tmux", "-S", str(sock), "list-sessions", "-F", "#{session_name}"], capture_output=True, text=True
    )
    if cp.returncode == 0:
        return [s for s in cp.stdout.split() if s]
    return [] if "no sessions" in cp.stderr else None


def _remove_legacy_system_units(uid: int) -> list[str]:
    """Stop, disable and remove the old-named system units (TD-060), refused while their server holds a
    session: stopping `agentorc-tmux` ends every session in it."""
    present = [u for u in LEGACY_SYSTEM_UNITS if (SYSTEM_DIR / u).exists()]
    if not present:
        return []
    live = _server_sessions(uid)
    if live is None or live:
        raise RuntimeError(
            f"the old units ({', '.join(present)}) still run a tmux server with sessions "
            f"({', '.join(live or ['unreadable'])}): close them, then run this again"
        )
    subprocess.run(["systemctl", "disable", "--now", *present], capture_output=True, text=True)
    for u in present:
        (SYSTEM_DIR / u).unlink(missing_ok=True)
    subprocess.run(["systemctl", "daemon-reload"], capture_output=True, text=True)
    return present


def install_system() -> str:
    """`ao service install --system`, as root (design §4.1): the tmux unit and the watch's service and
    timer (§4.10) written into `/etc/systemd/system`, then `daemon-reload` and `enable --now` of the
    tmux unit and the timer. The text is **made again here**
    for `SUDO_USER`, never read from the staged files: they are the person's, and any session can
    write them, so copying them would hand root to whatever rewrote them. Refused for anyone but root,
    naming the line; without a person to run it as; and while a server not the unit's still answers
    on the person's default socket — two servers on one socket orphan every session in the first."""
    import pwd

    if os.geteuid() != 0:
        raise PermissionError(f"the tmux system unit is root's to install: run `{system_line()}`")
    person = os.environ.get("SUDO_USER") or ""
    try:
        pw = pwd.getpwnam(person) if person and person != "root" else None
    except KeyError:
        pw = None
    if pw is None:
        raise RuntimeError(
            f"no person to run the tmux server as (SUDO_USER={person or 'unset'}): run `{system_line()}`"
        )
    _remove_legacy_system_units(pw.pw_uid)
    active = subprocess.run(["systemctl", "is-active", f"{TMUX_UNIT}.service"], capture_output=True, text=True)
    if active.stdout.strip() != "active" and _server_answers(pw.pw_uid):
        raise RuntimeError(
            f"a tmux server already answers on {person}'s default socket: stop the teams and that server "
            "first (every session in it ends), then run this again"
        )
    written = []
    for name, text in system_units(person, pw.pw_uid, pw.pw_dir).items():
        target = SYSTEM_DIR / name
        target.write_text(text)
        target.chmod(0o644)
        written.append(str(target))
    for args in (("daemon-reload",), ("enable", "--now", f"{TMUX_UNIT}.service", f"{WATCH_UNIT}.timer")):
        cp = subprocess.run(["systemctl", *args], capture_output=True, text=True)
        if cp.returncode != 0:
            raise RuntimeError(cp.stderr.strip() or cp.stdout.strip())
    return written


def tmux_placement() -> str:
    """Where the running tmux server is (design §4.1): its system unit, under the user manager (a
    warning: one stop of `systemd --user` ends every session), elsewhere, or no server."""
    from sessionorc import identity
    from sessionorc.tmux import Tmux

    try:
        pid = Tmux().server_pid()
    except Exception:  # noqa: BLE001 — no tmux at all reads as no server
        pid = None
    if not pid:
        return "tmux: no server"
    cgroup = identity.LinuxProc().cgroup(pid)
    runs = identity.server_placement(cgroup)
    if runs == "system":
        return f"ok: tmux — server {pid}, system unit {TMUX_UNIT}.service"
    if runs == "user":
        # §4.7's words for the doctor's warning
        return (
            f"warning: tmux — server {pid} under the user manager ({cgroup}): a stop of `systemd --user` "
            "ends every session; `ao service install` prints the system unit"
        )
    return f"tmux: server {pid}, not under systemd ({cgroup or 'cgroup unknown'})"


def watch_reading() -> dict[str, Any]:
    """Whether the watch stands (design §4.7 **agent**, §4.10): its timer's load and active states and
    its last run, `LastTriggerUSec` in systemd's words (*n/a* before the first). A read any user may
    make of a system unit; `{"loaded": False}` with no systemd at all."""
    try:
        cp = subprocess.run(
            [
                "systemctl",
                "show",
                f"{WATCH_UNIT}.timer",
                "-p",
                "LoadState",
                "-p",
                "ActiveState",
                "-p",
                "LastTriggerUSec",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return {"loaded": False}
    got = dict(ln.split("=", 1) for ln in cp.stdout.splitlines() if "=" in ln)
    return {
        "loaded": got.get("LoadState") == "loaded",
        "active": got.get("ActiveState", ""),
        "last": got.get("LastTriggerUSec", ""),
    }


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


def install(
    *, bind: str = DEFAULT_BIND, port: int = DEFAULT_PORT, home: str | None = None, start: bool = True
) -> list[str]:
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for name in UNITS:
        p = UNIT_DIR / f"{name}.service"
        p.write_text(unit_text(name, bind=bind, port=port, home=home or os.environ.get("SHIFTLEAD_HOME")))
        written.append(str(p))
    # The wheel of what was just installed — what a container node is provisioned from (design
    # §4.4a "A container node", TD-057 step 3c.2) — is written **before** the units restart: the
    # restarted agent takes its nodes' `hello`s at once and names the build it would provision
    # from the newest wheel, so a wheel written afterwards left a window in which a node could be
    # re-provisioned from the previous build (seen live at the promote of PR #225, 2026-09-18).
    # Never fatal to the promote, whatever it raises (a disk that refuses the directory, a `pip`
    # that cannot start): first in line, it must not be what stops the units coming up on the new
    # code (review of PR #227). A node then stays on the wheel the home already had.
    from sessionorc import containers

    try:
        wheel = containers.write_wheel()
    except Exception as e:  # noqa: BLE001
        print(f"shiftlead: the wheel could not be written ({type(e).__name__}: {e}); units go ahead", file=sys.stderr)
        wheel = None
    if wheel is not None:
        written.append(str(wheel))
    # At the home the directory becomes a work tree that tracks its three definition files (design
    # §4.9 *What is left at the home has a history*, TD-229); never on a node, never fatal to the units.
    try:
        tree = _home_history(home)
    except Exception as e:  # noqa: BLE001
        print(f"shiftlead: the home's history could not be set up ({type(e).__name__}: {e})", file=sys.stderr)
        tree = None
    if tree is not None:
        print(f"shiftlead: {tree} now keeps the history of org.yml, profiles.yml and settings.yml")
    _systemctl("daemon-reload")
    # Always enable (a reboot must not need a human, design §8); --no-start only defers the start.
    cp = _systemctl("enable", *(["--now"] if start else []), *[f"{u}.service" for u in UNITS])
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or cp.stdout.strip())
    if start:
        # `enable --now` leaves an already-running unit on its old ExecStart; a re-install that
        # re-points the units (dev venv → stable install) must restart to take effect. Safe: the
        # agent unit never takes tmux down (KillMode=process); the UI's terminals reconnect.
        _systemctl("restart", *[f"{u}.service" for u in UNITS])
    return written


def _home_history(home: str | None) -> str | None:
    """`~/.shiftlead` made a git work tree tracking `org.yml`, `profiles.yml` and `settings.yml`, when
    this host is the home and it is not one yet: its `.git`, or None."""
    from sessionorc import defs, hosts, paths

    if hosts.home_name() != hosts.local_host().name:
        return None  # a node: its settings are the home's replica, and nothing of it is tracked
    root = Path(home).expanduser() if home else paths.home()
    return str(root / ".git") if defs.init(root) else None


def uninstall() -> None:
    _systemctl("disable", "--now", *[f"{u}.service" for u in UNITS])
    for name in UNITS:
        (UNIT_DIR / f"{name}.service").unlink(missing_ok=True)
    _systemctl("daemon-reload")


def status() -> str:
    lines = []
    for name in UNITS:
        cp = _systemctl("is-active", f"{name}.service")
        lines.append(f"{name}: {cp.stdout.strip() or cp.stderr.strip()}")
    linger = subprocess.run(
        ["loginctl", "show-user", getpass.getuser(), "-p", "Linger"], capture_output=True, text=True
    )
    lines.append(linger.stdout.strip() or "Linger: unknown")
    lines.append(tmux_placement())
    watch = watch_reading()
    lines.append(
        f"{WATCH_UNIT}.timer: {watch.get('active') or 'inactive'}"
        if watch["loaded"]
        else f"{WATCH_UNIT}.timer: not installed"
    )
    return "\n".join(lines)
