"""Grok Build adapter (design §4.3 *The third adapter: Grok Build*, TD-1550, TD-1637): the launch, the profile's
home and credentials, and the hook file the launch writes into that home.

The tool reads hooks only from files, so the launch writes `<GROK_HOME>/hooks/shiftlead.json` — ShiftLead's own
file in the home's hook directory, beside any of the person's — naming `shiftlead-hook --adapter grok` for every
event the state feed reads. A profile names a `config_dir` of its own (`own_home`, §4.2a), so the person's own
`~/.grok` is never written. Read against the installed 1.0.77 (`50ca579fa996`, 2026-11-14): `--session-id`,
`--resume`, `--always-approve`, `--permission-mode default` and `-m` are its flags.

Not registered under the `shiftlead.adapters` entry points yet: the conformance suite tests every registered
agent adapter against fixtures captured from the real tool, and those land with the state feed (TD-1637).
"""

from __future__ import annotations

import json
import os
import shlex
import sys
import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path

from sessionorc.adapters import LaunchSpec, read_version
from sessionorc.models import Confidence, State
from sessionorc.tmux import PaneInfo
from shiftlead import profiles as profiles_mod
from shiftlead.profiles import Profile

NAME = "grok"
ADAPTER_FLAG = "--adapter"  # `shiftlead-hook --adapter grok`, read from argv before any import (§4.1)
OWN_HOME = Path("~/.grok")  # the tool's own default home, never written (§4.2a `own_home`)
BINARY = OWN_HOME / "bin" / "grok"  # the install's link, by absolute path (§4.3 `launch`)
INSTALL_LINE = "curl -fsSL https://x.ai/cli/install.sh | bash"  # the person's, by hand (§4.3 *The install*)
HOOK_FILE = Path("hooks") / "shiftlead.json"  # under the profile's GROK_HOME
# every event the state feed reads (§4.3 *The state feed*; the guide's *Hook Events*)
HOOK_EVENTS = (
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PermissionDenied",
    "Notification",
    "Stop",
    "StopFailure",
    "StopCancelled",
    "SubagentStart",
    "SubagentStop",
)
HOOK_TIMEOUT_S = 10  # set on every entry, since the tool's defaults differ by event (5, 30, 600, 1.5 s)
ALWAYS_APPROVE = ["--always-approve"]  # an unattended launch under `permission_prompts: skip` (§4.2a)
# the tool's `auto` mode lets a classifier approve a command before any prompt (§4.3 `asking_args`)
ASKING_ARGS = ["--permission-mode", "default"]
# what every launch sets (§4.3): the version pinned, the other tools' hooks and MCP servers off, folder trust
# ungated per process, a first permission prompt's preselection the one call, `SessionEnd`'s hook default
# lifted, and the API-key fallback cleared so an expired sign-in never falls to a key on someone else's bill
LAUNCH_ENV = {
    "GROK_DISABLE_AUTOUPDATER": "1",
    "GROK_CLAUDE_HOOKS_ENABLED": "false",
    "GROK_CURSOR_HOOKS_ENABLED": "false",
    "GROK_CLAUDE_MCPS_ENABLED": "false",
    "GROK_CURSOR_MCPS_ENABLED": "false",
    "GROK_FOLDER_TRUST": "0",
    "GROK_DEFAULT_SELECTED_PERMISSION": "allow_once",
    "GROK_SESSION_END_HOOKS_TIMEOUT_MS": str(HOOK_TIMEOUT_S * 1000),
    "XAI_API_KEY": "",
    "GROK_CODE_XAI_API_KEY": "",
}
NO_HOME = "a Grok profile needs a config_dir of its own"


def hook_path() -> str:
    """`bin/shiftlead-hook` beside the host agent's own interpreter, never a `PATH` lookup, so a promote keeps it
    and a scratch host agent writes its own venv's path (§4.3 *The hooks*)."""
    return str(Path(sys.executable).parent / "shiftlead-hook")


def hook_settings(hook_cmd: str) -> dict:
    """The hook file's contents: one command, `<hook_cmd> --adapter grok`, on each of `HOOK_EVENTS`, no matcher,
    a 10-second `timeout` each. Nothing in it varies per launch: the hook reads the launch's environment."""
    command = f"{shlex.quote(hook_cmd)} {ADAPTER_FLAG} {NAME}"
    entry = {"type": "command", "command": command, "timeout": HOOK_TIMEOUT_S}
    return {"hooks": {ev: [{"hooks": [dict(entry)]}] for ev in HOOK_EVENTS}}


def write_hook_file(home: Path, hook_cmd: str) -> Path:
    """`<home>/hooks/shiftlead.json`, written when it is missing or differs from the wanted copy, atomically (a
    temporary file renamed over it, since the walk's host agent and the live one can launch on one home). An
    `OSError` is the caller's to refuse the launch with."""
    path = home / HOOK_FILE
    text = json.dumps(hook_settings(hook_cmd), indent=2) + "\n"
    try:
        if path.read_text(encoding="utf-8") == text:
            return path
    except (OSError, UnicodeDecodeError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".shiftlead.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


class GrokAdapter:
    name = NAME
    label = "Grok"  # the tool's display name: the usage chip's first word, never a key (§4.3, TD-122)
    state_source: Confidence = "hook"
    own_home = OWN_HOME.expanduser()  # a profile names a config_dir of its own (§4.2a, TD-1550)
    permission_channel = False  # a Grok hook cannot answer a prompt (§4.3 *No permission channel*)
    start_context = False  # no Grok hook hands the model context at the start (§4.3 `start_context`)
    asking_args = ASKING_ARGS  # added to an unattended launch under `permission_prompts: all` (§4.3, TD-823)
    implements: frozenset[str] = frozenset()

    def __init__(self, binary: str | None = None, hook_cmd: str | None = None):
        self.binary = binary or str(BINARY.expanduser())
        self._hook_cmd = hook_cmd

    def tool_version(self, env: Mapping[str, str]) -> str | None:
        """The tool's version at a seat's launch (§4.3 *An upgraded seat tool asks for the smoke*, TD-1650)."""
        return read_version(self.binary, env)

    def launch(
        self, *, profile: str, resume: str | None, prompt: str | None, unattended: bool, cwd: Path, name: str = ""
    ) -> LaunchSpec:
        """The binary by absolute path, refused in words where it is missing; `--session-id` with an id of
        ShiftLead's, or `--resume <id>` from the record's directory; `-m` for the profile's model;
        `--always-approve` on an unattended launch under `permission_prompts: skip` only, `asking_args` under
        `all`. `GROK_HOME` is the profile's `config_dir`, and the hook file is written into it first."""
        prof = profiles_mod.get(profile or None)
        if not prof.config_dir:
            raise ValueError(f"{NO_HOME} ({prof.name})")
        if not Path(self.binary).is_file():
            raise ValueError(f"Grok Build is not installed at {self.binary} — the person installs it: {INSTALL_LINE}")
        home = Path(prof.config_dir).expanduser()
        try:
            write_hook_file(home, self._hook_cmd or hook_path())
        except OSError as e:
            raise ValueError(f"cannot write the Grok hook file into {home / HOOK_FILE}: {e}") from e
        adapter_id = resume or str(uuid.uuid4())
        argv = [self.binary, *(["--resume", resume] if resume else ["--session-id", adapter_id])]
        if prof.model:
            argv += ["--model", prof.model]
        argv += prof.extra_args
        if unattended:
            args = prof.unattended_args or ALWAYS_APPROVE
            argv += args if prof.permission_prompts == "skip" else [a for a in args if a not in ALWAYS_APPROVE]
            if prof.permission_prompts == "all":
                argv += self.asking_args
        env = {"GROK_HOME": str(home), **LAUNCH_ENV}
        # the prompt is typed at the composer by the host agent once `SessionStart` reports (§4.1, TD-339)
        return LaunchSpec(argv=argv, env=env, adapter_id=adapter_id, first_prompt=prompt or None, model=prof.model)

    def classify(self, pane: PaneInfo | None, tail: list[str]) -> State | None:
        return None  # hook-fed: the state comes from the hooks

    def default_home(self, env: Mapping[str, str]) -> Path:
        """The home a launch would use with no `config_dir` (§4.3's Protocol block, TD-1648): `$GROK_HOME`, else
        `~/.grok`, the variable ignored where `env` holds `SHIFTLEAD_SESSION`, a session's being its own
        launch's. What the walk and the seat smoke refuse."""
        own = None if "SHIFTLEAD_SESSION" in env else env.get("GROK_HOME")
        return Path(own).expanduser() if own else self.own_home

    def credentials_ok(self, profile: Profile) -> bool | None:
        """Whether the home is signed in: `<GROK_HOME>/auth.json` exists (§4.3 *Sign-in*). None where it does
        not, or the profile names no home; signing a home in is the person's (`GROK_HOME=<dir> grok login`)."""
        if not profile.config_dir:
            return None
        return True if (Path(profile.config_dir).expanduser() / "auth.json").is_file() else None

    def setup_note(self) -> dict | None:
        """What the host agent tells the person once per key (§4.3 `launch`): None with no Grok profile; `key` None
        where the binary is there; else the missing binary's path as `key` and the note's `text`. The binary is the
        machine's, not a home's, so one note covers every Grok profile."""
        try:
            profs, _ = profiles_mod.load()
        except (OSError, ValueError, TypeError, AttributeError):
            return None
        if not any(p.adapter == self.name for p in profs.values()):
            return None
        if Path(self.binary).is_file():
            return {"key": None}
        text = (
            f"Grok Build is not installed at {self.binary}, so a Grok session is refused. The install is yours, "
            f"by hand, once on this machine (it checks no checksum, edits your shell's rc file and links grok in "
            f"~/.grok/bin):\n\n{INSTALL_LINE}\n\nthen sign each Grok profile's home in: "
            "GROK_HOME=<its config_dir> grok login (design §4.3)."
        )
        return {"key": f"missing:{self.binary}", "text": text}
