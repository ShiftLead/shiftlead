"""Gemini CLI adapter (design §4.3 *The second adapter: Gemini CLI*, TD-112, TD-785): hook-fed state,
the launch and its settings layer, the profile's home and credentials.

Hooks reach a launched session through `GEMINI_CLI_SYSTEM_SETTINGS_PATH`, the tool's highest-precedence
settings file, whose `hooks` concatenate with the person's rather than replace them — so nothing in the
person's own `settings.json` is edited and hand-started sessions are untouched. Its hooks run
`shiftlead-hook --adapter gemini`, which finds its session from `SHIFTLEAD_SESSION`.

Not yet registered under the `shiftlead.adapters` entry points: the conformance suite tests every
registered agent adapter against fixtures captured from the real tool, which TD-785's later slice records.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import uuid
from pathlib import Path

from sessionorc import paths
from sessionorc.adapters import LaunchSpec
from sessionorc.models import Confidence, Pending, State
from sessionorc.screen import Match
from sessionorc.tmux import PaneInfo
from shiftlead import profiles as profiles_mod
from shiftlead.adapters.claude_code import _resolves, hook_command
from shiftlead.profiles import Profile

log = logging.getLogger("shiftlead.adapters.gemini")

NAME = "gemini"
ADAPTER_FLAG = "--adapter"  # `shiftlead-hook --adapter gemini`: read from argv before any import (§4.1)
HOOK_EVENTS = ("SessionStart", "SessionEnd", "BeforeAgent", "AfterAgent", "BeforeTool", "AfterTool", "Notification")
HOOK_TIMEOUT_MS = 10_000  # the tool's `timeout` is in milliseconds; every hook here is fire-and-forget
# where the tool sits when it was installed with npm's user prefix: off `PATH` outside a login shell
NPM_BINARY = Path("~/.npm-global/bin/gemini")
YOLO = ["--approval-mode", "yolo"]  # an unattended launch under `permission_prompts: skip` (§4.2a)
# The layer's settings besides its hooks (design §4.3 `launch`): no on-screen notification hooks, no
# tips or banner, the version the build was read against pinned, and the title the state check reads
# turned on, so the person's own settings cannot turn it off.
LAYER_SETTINGS = {
    "hooksConfig": {"notifications": False},
    "general": {"enableAutoUpdate": False},
    "ui": {
        "hideTips": True,
        "hideBanner": True,
        "dynamicWindowTitle": True,
        "hideWindowTitle": False,
        "showStatusInTitle": False,
    },
}
# The title's leading glyph and the state it means (design §4.3 *Two gaps*): `◇  Ready`, `✦  Working…`
# responding, `⏲  Working…` its shell quiet with no output, `✋  Action Required` a confirmation or that
# shell waiting for input. The glyph alone is matched; the words and the context after it are not.
TITLE_STATES: dict[str, State] = {"◇": "idle", "✦": "working", "⏲": "working", "✋": "needs-you"}


def home(profile: Profile) -> Path:
    """The profile's home (`GEMINI_CLI_HOME`): its `config_dir`, else the tool's own, `~` — the tool
    keeps its `.gemini/` under it."""
    return profile.config_dir or Path(os.environ.get("GEMINI_CLI_HOME") or "~").expanduser()


def layer_file(profile: Profile, unattended: bool = False) -> Path:
    suffix = "+unattended" if unattended else ""
    return paths.home() / "gemini-settings" / f"{profile.name}{suffix}.json"


def layer_settings(hook_cmd: str = "shiftlead-hook") -> dict:
    """The settings layer a launch names in `GEMINI_CLI_SYSTEM_SETTINGS_PATH` (design §4.3 `launch`): a
    hook on each of `HOOK_EVENTS` calling `<hook_cmd> --adapter gemini`, and `LAYER_SETTINGS`."""
    command = f"{shlex.quote(hook_cmd)} {ADAPTER_FLAG} {NAME}"
    hook = {"type": "command", "command": command, "timeout": HOOK_TIMEOUT_MS}
    return {"hooks": {ev: [{"hooks": [dict(hook)]}] for ev in HOOK_EVENTS}, **json.loads(json.dumps(LAYER_SETTINGS))}


def write_layer(profile: Profile, unattended: bool = False) -> Path:
    """Write the layer for this launch, one file per profile and launch shape, so concurrent launches
    never overwrite each other's choice."""
    p = layer_file(profile, unattended)
    p.parent.mkdir(parents=True, exist_ok=True)
    cmd = hook_command()
    if cmd is None:
        log.warning(
            "shiftlead-hook not on PATH (%s); hooks for profile %s may never fire", os.environ.get("PATH"), profile.name
        )
        cmd = "shiftlead-hook"
    p.write_text(json.dumps(layer_settings(cmd), indent=1), encoding="utf-8")
    return p


def layer_reading(profile: Profile) -> list[dict]:
    """Each layer written for `profile` and the commands it names, with whether each resolves (`ao
    doctor`'s hooks check, design §4.7) — the shape Claude Code's adapter reports."""
    out: list[dict] = []
    for p in sorted((paths.home() / "gemini-settings").glob(f"{profile.name}*.json")):
        if p.stem != profile.name and not p.stem.startswith(f"{profile.name}+"):
            continue  # another profile whose name begins with this one's
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            cmds = [str(h.get("command", "")) for g in doc.get("hooks", {}).values() for e in g for h in e["hooks"]]
        except (OSError, ValueError, AttributeError, TypeError, KeyError) as e:
            out.append({"path": str(p), "error": str(e) or type(e).__name__, "commands": []})
            continue
        out.append({"path": str(p), "commands": [{"command": c, "resolves": _resolves(c)} for c in sorted(set(cmds))]})
    return out


def title_state(pane_title: str) -> State | None:
    """The state the tool's title says (design §4.3 *Two gaps*): its leading glyph alone, None for a
    title that leads with none of `TITLE_STATES` (a shell's, the tool's before it mounts)."""
    text = (pane_title or "").lstrip()
    return TITLE_STATES.get(text[:1]) if text else None


class GeminiAdapter:
    name = NAME
    label = "Gemini"  # the tool's display name: the usage chip's first word, never a key (§4.3, TD-122)
    state_source: Confidence = "hook"
    # the tool writes its state into its terminal title: the tick asks `explain` with the pane's title
    # and writes its verdict with `confidence: title` (design §4.2 *A title the tool writes its state into*)
    state_in_title = True
    # no hook answers a confirmation: a pending permission is answered in the terminal (§4.3, §4.5a)
    permission_channel = False
    # the optional methods it has, tested by the conformance suite (design §4.3, TD-112): none yet — the
    # composer, title, reads and the rest come with TD-785's later slices
    implements: frozenset[str] = frozenset()

    def __init__(self, binary: str | None = None):
        self._binary = binary

    @property
    def binary(self) -> str:
        """The tool by absolute path (it is on `PATH` only in a login shell), found once and kept."""
        if self._binary is None:
            npm = NPM_BINARY.expanduser()
            found = shutil.which("gemini") or (str(npm) if npm.is_file() else None)
            self._binary = found or "gemini"
        return self._binary

    def launch(
        self, *, profile: str, resume: str | None, prompt: str | None, unattended: bool, cwd: Path, name: str = ""
    ) -> LaunchSpec:
        prof = profiles_mod.get(profile or None)
        adapter_id = resume or str(uuid.uuid4())
        # a resume names an id the tool finds by its project, so it launches from the record's directory
        argv = [self.binary, *(["--resume", resume] if resume else ["--session-id", adapter_id])]
        if prof.model:
            argv += ["--model", prof.model]
        argv += prof.extra_args
        if unattended:
            args = prof.unattended_args or YOLO
            argv += args if prof.permission_prompts == "skip" else _without_yolo(args)
        env = {
            "GEMINI_CLI_SYSTEM_SETTINGS_PATH": str(write_layer(prof, unattended)),
            # the tool's per-process trust, read before its trust file: an untrusted folder runs no hook
            # at all and downgrades yolo to `default`, so trust is the state feed's precondition; nothing
            # is written to the person's `trustedFolders.json` (design §4.3 `quirks`)
            "GEMINI_CLI_TRUST_WORKSPACE": "true",
            "GEMINI_FORCE_FILE_STORAGE": "true",  # two profiles never share an OS keychain entry
            # read only under Vertex auth or as the SDK's fallback: a profile's billing never hangs on it
            "GOOGLE_API_KEY": "",
        }
        if prof.config_dir:
            env["GEMINI_CLI_HOME"] = str(prof.config_dir)
        if name:
            env["CLI_TITLE"] = name  # the session's name, which the tool puts in its title
        # the prompt is typed at the composer by the host agent once `SessionStart` reports (§4.1, TD-339)
        return LaunchSpec(argv=argv, env=env, adapter_id=adapter_id, first_prompt=prompt or None, model=prof.model)

    def classify(self, pane: PaneInfo | None, tail: list[str]) -> State | None:
        return None  # hook-fed: the screen has no opinion; the title's check is the tick's (§4.3)

    def explain(self, tail: list[str], title: str = "") -> Match | None:
        """The title's verdict (design §4.3 *Two gaps*): the state its leading glyph says, `✋` a question
        with no text — the tick writes the text by the state it replaces. The tail is not read."""
        state = title_state(title)
        if state is None:
            return None
        pending = Pending(kind="question", text="") if state == "needs-you" else None
        return Match(rule=f"title {title.lstrip()[0]}", state=state, evidence=[title.strip()], pending=pending)

    # -- account ---------------------------------------------------------------------------------

    def credentials_ok(self, profile: Profile) -> bool | None:
        """Whether the home can start without the auth picker (design §4.3): its `settings.json` names
        `security.auth.selectedType` and the credential exists — the file store, its older name, or
        `GEMINI_API_KEY` in the environment. None for no credential; signing in is the person's."""
        gem = home(profile) / ".gemini"
        try:
            doc = json.loads((gem / "settings.json").read_text(encoding="utf-8"))
            selected = ((doc.get("security") or {}).get("auth") or {}).get("selectedType")
        except (OSError, ValueError, AttributeError):
            selected = None
        if not selected:
            return None
        if os.environ.get("GEMINI_API_KEY"):
            return True
        return True if any((gem / f).is_file() for f in ("gemini-credentials.json", "oauth_creds.json")) else None

    def doctor_profiles(self) -> list[dict]:
        """What `ao doctor` reads of each Gemini profile (design §4.7, §4.3): its home, its credential, a
        metered key, a `GOOGLE_API_KEY` in the host agent's environment (a precaution's note, since the
        launch clears it), and its layers with whether `shiftlead-hook --adapter gemini` resolves."""
        try:
            profs, _ = profiles_mod.load()
        except (OSError, ValueError, TypeError, AttributeError) as e:
            return [{"error": f"profiles.yml: {e}"}]
        out: list[dict] = []
        for prof in profs.values():
            if prof.adapter != self.name:
                continue
            row: dict = {
                "profile": prof.name,
                "account": prof.account or prof.name,
                "config_dir": str(home(prof)),
                "metered": prof.metered,
                "credentials": None if prof.metered else self.credentials_ok(prof),
                "layers": layer_reading(prof),
                "login": f"GEMINI_CLI_HOME={home(prof)} {self.binary}",
            }
            if prof.metered:
                row["key"] = bool(os.environ.get("GEMINI_API_KEY"))
            if os.environ.get("GOOGLE_API_KEY"):
                row["note"] = "GOOGLE_API_KEY is set in the host agent's environment; each launch clears it"
            out.append(row)
        return out

    def account_for(self, profile: str) -> str | None:
        try:
            prof = profiles_mod.get(profile or None)
        except (KeyError, ValueError):
            return None
        return prof.account or prof.name


def _without_yolo(args: list[str]) -> list[str]:
    """`args` less the approval mode `yolo` (and `--yolo`): under `permission_prompts: ask` the tool asks."""
    out: list[str] = []
    for a in args:
        if out and out[-1] == "--approval-mode" and a == "yolo":
            out.pop()
        elif a not in ("--yolo", "-y", "--approval-mode=yolo"):
            out.append(a)
    return out
