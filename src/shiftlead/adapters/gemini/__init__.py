"""Gemini CLI adapter (design §4.3 *The second adapter: Gemini CLI*, TD-112, TD-785): hook-fed state,
the launch and its settings layer, the profile's home and credentials.

Hooks reach a launched session through `GEMINI_CLI_SYSTEM_SETTINGS_PATH`, the tool's highest-precedence
settings file, whose `hooks` concatenate with the person's rather than replace them — so nothing in the
person's own `settings.json` is edited and hand-started sessions are untouched. Its hooks run
`shiftlead-hook --adapter gemini`, which finds its session from `SHIFTLEAD_SESSION`. The tool reads that
file only when root owns it, so it is the machine's layer, `MACHINE_LAYER`, installed by the person once
with the line `ao doctor` prints from the wanted copy ShiftLead writes (TD-871, TD-875).

Registered under the `shiftlead.adapters` entry points, so the conformance suite tests it against the
fixtures captured from the real tool (`tests/conformance/fixtures/gemini/`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shlex
import shutil
import stat
import sys
import uuid
from pathlib import Path

from sessionorc import paths
from sessionorc.adapters import LaunchSpec, Link, MailDelivery, Transcript
from sessionorc.models import Confidence, Pending, State
from sessionorc.screen import Manifest, Match, painted_text
from sessionorc.tmux import PaneInfo
from shiftlead import profiles as profiles_mod
from shiftlead.adapters.claude_code import _resolves, write_context_file
from shiftlead.adapters.gemini import transcript as transcript_mod
from shiftlead.adapters.gemini.hook import START_CONTEXT_ENV
from shiftlead.profiles import Profile

log = logging.getLogger("shiftlead.adapters.gemini")

NAME = "gemini"
RULES_FILE = Path(__file__).with_name("screen_rules.toml")  # its screen-rule manifest (§4.3, TD-944)
ADAPTER_FLAG = "--adapter"  # `shiftlead-hook --adapter gemini`: read from argv before any import (§4.1)
HOOK_EVENTS = ("SessionStart", "SessionEnd", "BeforeAgent", "AfterAgent", "BeforeTool", "AfterTool", "Notification")
HOOK_TIMEOUT_MS = 10_000  # the tool's `timeout` is in milliseconds; every hook here but the start is fire-and-forget
# `SessionStart` runs the repo's start hooks itself (design §4.3 *The repo's start hooks*): at or above
# the runner's own bound, `hook.START_HOOKS_TIMEOUT`, so the tool never cancels it first
START_TIMEOUT_MS = 180_000  # the runner, its `git` read (10 s) and the report (3 s)
# where the tool sits when it was installed with npm's user prefix: off `PATH` outside a login shell
NPM_BINARY = Path("~/.npm-global/bin/gemini")
YOLO = ["--approval-mode", "yolo"]  # an unattended launch under `permission_prompts: skip` (§4.2a)
# no `asking_args` (§4.3): under `permission_prompts: all` the launch is `ask`'s, yolo dropped and nothing added
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
# The title's bracketed context, `CLI_TITLE` (design §4.3 `title`): `◇  Ready (name)`, the name's own
# brackets kept; a title not led by a state glyph (a shell's `user@host: ~/d (copy)`) has none
TITLE_NAME = re.compile(rf"^[{''.join(TITLE_STATES)}]\s+[^(]*\((.+)\)$")
# The composer (design §4.3 `composer`, read 2026-10-21 on 0.64.0): an input box whose top border is a row
# of `▄`, its first row the prompt glyph (`>`, `*` under yolo, `!` in shell mode). A submitted prompt is
# drawn in the same box in the history above, without the reverse-video cursor the composer holds.
COMPOSER_TOP, COMPOSER_BOTTOM = "▄", "▀"
COMPOSER_ROW = re.compile(r"^\s*[>*!] ")
CURSOR = "\x1b[7m"
# painted grey, not faint, so read as empty by its words
PLACEHOLDER = "Type your message or @path/to/file"


def home(profile: Profile) -> Path:
    """The profile's home (`GEMINI_CLI_HOME`): its `config_dir`, else the tool's own, `~` — the tool
    keeps its `.gemini/` under it."""
    return profile.config_dir or Path(os.environ.get("GEMINI_CLI_HOME") or "~").expanduser()


# The machine's layer (design §4.3 `launch`, TD-871): the tool reads a system settings file only when root
# owns it and every directory above it, so the person installs it once with `INSTALL_LINE`; nothing here
# calls `sudo`.
MACHINE_LAYER = Path("/etc/shiftlead/gemini-settings.json")
INSTALL_LINE = (
    "sudo install -d -o root -g root -m 0755 /etc/shiftlead && sudo install -o root -g root -m 0644 "
    "~/.shiftlead/gemini-settings/layer.json /etc/shiftlead/gemini-settings.json"
)
REFUSED = "the Gemini layer is not installed — run the line `ao doctor` prints"


def wanted_file() -> Path:
    """The wanted copy: what `MACHINE_LAYER` should hold, one file for every profile and launch shape."""
    return paths.home() / "gemini-settings" / "layer.json"


def hook_path() -> str:
    """`bin/shiftlead-hook` beside the host agent's own interpreter, never a `PATH` lookup, so the installed
    file does not move with a unit's `PATH` and a promote keeps it (design §4.3 *The file is kept stable*)."""
    return str(Path(sys.executable).parent / "shiftlead-hook")


def layer_settings(hook_cmd: str = "shiftlead-hook") -> dict:
    """The settings layer a launch names in `GEMINI_CLI_SYSTEM_SETTINGS_PATH` (design §4.3 `launch`): a
    hook on each of `HOOK_EVENTS` calling `<hook_cmd> --adapter gemini`, and `LAYER_SETTINGS`."""
    command = f"{shlex.quote(hook_cmd)} {ADAPTER_FLAG} {NAME}"
    hooks = {ev: [{"hooks": [{"type": "command", "command": command, "timeout": _timeout(ev)}]}] for ev in HOOK_EVENTS}
    return {"hooks": hooks, **json.loads(json.dumps(LAYER_SETTINGS))}


def _timeout(event: str) -> int:
    return START_TIMEOUT_MS if event == "SessionStart" else HOOK_TIMEOUT_MS


def layer_text(hook: str) -> str:
    """The layer's bytes for a hook at `hook`: the wanted copy's here, a container node's with its own."""
    return json.dumps(layer_settings(hook), indent=1)


def write_layer() -> Path:
    """Write the wanted copy, the same bytes for every profile and launch, and remove the per-profile
    layers earlier builds wrote beside it (`<profile>[+unattended].json`), which the tool never read."""
    p = wanted_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    text = layer_text(hook_path())
    try:
        same = p.read_text(encoding="utf-8") == text
    except OSError:
        same = False
    if not same:  # whole or not at all: an overlapping launch reads the copy while it is written
        tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, p)
    for old in p.parent.glob("*.json"):
        if old != p:
            old.unlink(missing_ok=True)
    return p


def _lstat(p: Path) -> os.stat_result:
    return os.lstat(p)  # patched in tests, where no file is root's


def insecure(path: Path) -> str | None:
    """Why the tool would skip `path` as a system settings file, or None: root must own the file and every
    directory above it to `/`, symlinks on the way followed, and none may be writable by group or others —
    the tool's own test (0.64.0's `isFileAndDirectorySecureSync`)."""
    seen = 0
    p = Path(os.path.abspath(path))
    while True:
        st = _lstat(p)
        if stat.S_ISLNK(st.st_mode):
            seen += 1
            if seen > 40:
                return f"{p} loops"
            target = Path(os.readlink(p))
            p = Path(os.path.normpath(p.parent / target))
            continue
        if st.st_uid != 0:
            return f"{p} is not root-owned"
        if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            return f"{p} is writable by group or others"
        if p.parent == p:
            return None
        p = p.parent


def _commands(doc: dict) -> list[str]:
    return sorted({str(h.get("command", "")) for g in doc.get("hooks", {}).values() for e in g for h in e["hooks"]})


def machine_reading() -> dict:
    """The installed layer against the wanted copy: `state` is `ok`, `stale` (it differs, and launches),
    or one that refuses a launch — `missing`, `insecure`, `unresolved` (no hook command it names
    resolves) — with `why`, the commands it names and whether each resolves (design §4.3, §4.7)."""
    wanted = write_layer()
    out: dict = {"path": str(MACHINE_LAYER), "wanted": str(wanted), "install": INSTALL_LINE, "commands": []}
    try:
        text = MACHINE_LAYER.read_text(encoding="utf-8")
    except FileNotFoundError:
        return out | {"state": "missing", "why": "not installed"}
    except OSError as e:
        return out | {"state": "missing", "why": str(e) or type(e).__name__}
    try:
        why = insecure(MACHINE_LAYER)
    except OSError as e:
        why = str(e) or type(e).__name__
    if why:
        return out | {"state": "insecure", "why": why}
    try:
        cmds = _commands(json.loads(text))
    except (ValueError, AttributeError, TypeError, KeyError) as e:
        return out | {"state": "unresolved", "why": f"unreadable: {str(e) or type(e).__name__}"}
    out["commands"] = [{"command": c, "resolves": _resolves(c)} for c in cmds]
    if not any(c["resolves"] for c in out["commands"]):
        return out | {"state": "unresolved", "why": "names no hook command that resolves"}
    same = json.loads(text) == json.loads(wanted.read_text(encoding="utf-8"))
    return out | ({"state": "ok", "why": ""} if same else {"state": "stale", "why": "differs from the wanted copy"})


def layer_reading(profile: Profile | None = None) -> list[dict]:
    """The machine's layer read against the wanted copy (`ao doctor`'s hooks check, design §4.7): one
    file for every Gemini profile, in the shape Claude Code's adapter reports, with `gemini` the reading."""
    r = machine_reading()
    return [{"path": r["path"], "commands": r["commands"], "gemini": r}]


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
    # held from its start, through `SessionStart`'s `additionalContext` (design §4.3 `start_context`)
    start_context = True
    # the optional methods it has, tested by the conformance suite (design §4.3, TD-112): the rest come
    # with TD-786's later slices
    implements: frozenset[str] = frozenset({"composer", "context", "links", "mail", "spend", "title"})

    def __init__(self, binary: str | None = None, rules: Path | None = None):
        self._binary = binary
        self.rules = Manifest.load(rules or RULES_FILE)  # what neither hooks nor the title say (§4.3)

    @property
    def binary(self) -> str:
        """The tool by absolute path (it is on `PATH` only in a login shell), found once and kept."""
        if self._binary is None:
            npm = NPM_BINARY.expanduser()
            found = shutil.which("gemini") or (str(npm) if npm.is_file() else None)
            self._binary = found or "gemini"
        return self._binary

    def launch(
        self,
        *,
        profile: str,
        resume: str | None,
        prompt: str | None,
        unattended: bool,
        cwd: Path,
        name: str = "",
        start_context: str | None = None,
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
        layer = machine_reading()
        if layer["state"] in ("missing", "insecure", "unresolved"):
            # a session with no hooks never leaves its launch state (design §4.3 *A launch reads…*)
            raise ValueError(f"{REFUSED} ({MACHINE_LAYER}: {layer['why']})")
        env = {
            "GEMINI_CLI_SYSTEM_SETTINGS_PATH": str(MACHINE_LAYER),
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
        if start_context:
            # the hook reads it on every `SessionStart`, a resume's and a `/clear`'s too (design §4.3)
            env[START_CONTEXT_ENV] = str(write_context_file(adapter_id, start_context))
        # the prompt is typed at the composer by the host agent once `SessionStart` reports (§4.1, TD-339)
        return LaunchSpec(argv=argv, env=env, adapter_id=adapter_id, first_prompt=prompt or None, model=prof.model)

    def mail(self) -> MailDelivery:
        """An injection at the top of a turn (design §4.3 `mail`): `BeforeAgent`'s `additionalContext`
        carries the unread line; an idle session is woken by the doorbell's pane write, as Claude Code's."""
        return MailDelivery(how="turn", event="BeforeAgent")

    def classify(self, pane: PaneInfo | None, tail: list[str]) -> State | None:
        return None  # hook-fed: the screen has no opinion; the title's check is the tick's (§4.3)

    def explain(self, tail: list[str], title: str = "") -> Match | None:
        """The screen-rule manifest's verdict on the tail's painted text, else the title's (design §4.3 *The
        limit dialog is read off the screen*, *Two gaps*): so while the limit box is up its verdict stands
        over `✦`. The title's is the state its leading glyph says, `✋` a question with no text — the tick
        writes the text by the state it replaces. With no title, the manifest alone is read."""
        if (m := self.rules.explain([painted_text(r) for r in tail])) is not None:
            return m
        state = title_state(title)
        if state is None:
            return None
        pending = Pending(kind="question", text="") if state == "needs-you" else None
        return Match(
            rule=f"title {title.lstrip()[0]}", state=state, evidence=[title.strip()], pending=pending, title=True
        )

    def composer(self, tail_raw: list[str]) -> str | None:
        """The text in the composer (design §4.3 `composer`): the prompt row under the last input box's top
        border, stripped; "" when it holds the placeholder; None when that box holds no cursor (a dialog
        in its place, a history prompt the last box on screen) or no box is on screen. Faint text — the
        *Queued* lines above the box — is not counted. A multi-line text reads as its first row."""
        rows = [painted_text(r) for r in tail_raw]
        top = next((i for i in range(len(rows) - 1, -1, -1) if _border(rows[i])), None)
        if top is None:
            return None
        end = next((i for i in range(top + 1, len(rows)) if _border(rows[i], COMPOSER_BOTTOM)), len(rows))
        if not any(CURSOR in r for r in tail_raw[top + 1 : end]):
            return None
        for row in rows[top + 1 : end]:
            if m := COMPOSER_ROW.match(row):
                text = row[m.end() :].strip("\xa0 ")
                return "" if text == PLACEHOLDER else text
        return None

    def title(self, pane_title: str) -> str | None:
        """The session's name as the tool holds it (design §4.3 `title`): the title's bracketed context,
        which is `CLI_TITLE`; None for a title with none (a shell's, the tool's before it mounts)."""
        m = TITLE_NAME.match((pane_title or "").strip())
        return (m.group(1).strip() or None) if m else None

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
        launch clears it), and the machine's layer read against the wanted copy (`layer_reading`)."""
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

    def setup_note(self) -> dict | None:
        """What the host agent tells the person at its start and when `profiles.yml` changes (design §4.3
        *The person meets the step at setup*): None with no Gemini profile; `key` None when the machine's
        layer is the wanted copy; else `key` — the wanted copy's hash and the reading — and the note's
        `text`, which the host agent sends once per key."""
        try:
            profs, _ = profiles_mod.load()
        except (OSError, ValueError, TypeError, AttributeError):
            return None
        if not any(p.adapter == self.name for p in profs.values()):
            return None
        r = machine_reading()
        if r["state"] == "ok":
            return {"key": None}
        digest = hashlib.sha256(Path(r["wanted"]).read_bytes()).hexdigest()[:12]
        words = {"missing": "is not installed", "insecure": "is not root-owned", "stale": "is stale"}.get(
            r["state"], "names no hook command that resolves"
        )
        refused = "" if r["state"] == "stale" else " and is refused"
        text = (
            f"The Gemini layer {words}, so a Gemini session gets no hooks{refused}. "
            f"Run this once on this machine:\n\n{INSTALL_LINE}\n\n"
            f"Gemini CLI reads its hooks only from a settings file root owns ({MACHINE_LAYER}: {r['why']}); "
            "ShiftLead writes the file it wants and never runs sudo (design §4.3)."
        )
        return {"key": f"{digest}:{r['state']}", "text": text}

    def machine_layers(self, hook: str) -> list[tuple[str, str]]:
        """The machine layer a container node's root stage installs (design §4.3 *A container node needs
        no sudo*): where it goes and its bytes, naming the node's own hook."""
        return [(str(MACHINE_LAYER), layer_text(hook))]

    def account_for(self, profile: str) -> str | None:
        try:
            prof = profiles_mod.get(profile or None)
        except (KeyError, ValueError):
            return None
        return prof.account or prof.name

    def billing_for(self, profile: str) -> dict | None:
        """How the profile is billed (design §4.2a, TD-151): `{billing, prices}` as `profiles.yml` declares
        it. None for a profile that does not resolve."""
        try:
            prof = profiles_mod.get(profile or None)
        except (KeyError, ValueError):
            return None
        return {"billing": prof.billing, "prices": dict(prof.prices)}

    # -- reads (design §4.3 *Reads*, TD-786) -----------------------------------------------------

    def transcript_path(self, session_id: str, cwd: Path, profile: Profile | str | None = None) -> Path | None:
        """The session's chat under the profile's home: the file of a project's `chats/` named for the id
        whose first record names it (`transcript.find`); None when there is none."""
        prof = _profile(profile)
        return None if prof is None else transcript_mod.find(transcript_mod.chats_root(home(prof)), session_id)

    def read_transcript(
        self,
        session_id: str,
        cwd: Path,
        profile: str = "",
        *,
        before: int | None = None,
        turns: int = 20,
        raw: bool = False,
    ) -> Transcript | None:
        """The session's chat as neutral entries (design §4.3 `read_transcript`). None when there is no
        file, or the profile is unknown (never another account's home)."""
        p = self.transcript_path(session_id, cwd, profile)
        if p is None:
            return None
        try:
            return transcript_mod.read(p, before=before, turns=turns, raw=raw)
        except OSError:
            return None

    def context(self, session_id: str, cwd: Path, profile: str = "") -> dict | None:
        """The session's context size now (design §4.3 `context`, §6 rule 5): the last turn's input, the
        tool's window for its model. None when it cannot tell."""
        p = self.transcript_path(session_id, cwd, profile)
        return None if p is None else transcript_mod.context(p)

    def model_in_use(self, session_id: str, cwd: Path, profile: str = "") -> str | None:
        """The model the session's last turn ran on, None when it cannot tell."""
        p = self.transcript_path(session_id, cwd, profile)
        return None if p is None else transcript_mod.model(p)

    def links(self, session_id: str, cwd: Path, profile: str = "", *, cursor: int = 0) -> tuple[list[Link], int] | None:
        """The http/https URLs the session printed past byte `cursor` and the new cursor (design §4.3
        `links`). None when there is no file, or the profile is unknown."""
        p = self.transcript_path(session_id, cwd, profile)
        if p is None:
            return None
        try:
            return transcript_mod.links(p, cursor)
        except OSError:
            return None

    def spend(self, profile: str, cursors: dict[str, int] | None = None) -> dict:
        """Spend per turn for a profile (design §4.3 *Spend per turn*, *Reads*): `{turns, cursors, reason}`,
        every chat under the profile's home read from its cursor — sessions shiftlead did not start and
        subagents' chats (`chats/<parent id>/`) included, since both are billed. `conversation` is the
        chat's session, a subagent's its parent's; `cwd` the project's directory. `reason` is `ok`, or why
        nothing could be read, with the cursors unchanged."""
        before = {str(k): int(v) for k, v in (cursors or {}).items() if isinstance(v, int) and v >= 0}
        prof = _profile(profile)
        if prof is None:
            return {"turns": [], "cursors": before, "reason": "no_profile"}
        root = transcript_mod.chats_root(home(prof))
        if not root.is_dir():
            return {"turns": [], "cursors": before, "reason": f"no chats under {root}"}
        try:
            files = sorted(root.glob("*/chats/**/*.jsonl"))
        except OSError as e:
            return {"turns": [], "cursors": before, "reason": f"unreadable: {root}: {type(e).__name__}"}
        turns: list[dict] = []
        after: dict[str, int] = {}
        for p in files:
            key = str(p)
            subagent = p.parent.name != "chats"
            try:
                if p.stat().st_size == before.get(key, -1):
                    after[key] = before[key]
                    continue
                conversation = p.parent.name if subagent else (transcript_mod.session_of(p) or p.stem)
                got, after[key] = transcript_mod.turns(
                    p, before.get(key, 0), conversation, transcript_mod.cwd_of(p), subagent
                )
            except OSError:
                if key in before:
                    after[key] = before[key]
                continue
            turns.extend(got)
        return {"turns": turns, "cursors": after, "reason": "ok"}


def _profile(profile: Profile | str | None) -> Profile | None:
    """The profile itself, or by name; None for one that does not resolve (never another account's home)."""
    if isinstance(profile, Profile):
        return profile
    try:
        return profiles_mod.get(profile or None)
    except (KeyError, ValueError):
        return None


def _border(row: str, glyph: str = COMPOSER_TOP) -> bool:
    text = row.strip()
    return bool(text) and set(text) == {glyph}


def _without_yolo(args: list[str]) -> list[str]:
    """`args` less the approval mode `yolo` (and `--yolo`): under `permission_prompts: ask` or `all` the tool asks."""
    out: list[str] = []
    for a in args:
        if out and out[-1] == "--approval-mode" and a == "yolo":
            out.pop()
        elif a not in ("--yolo", "-y", "--approval-mode=yolo"):
            out.append(a)
    return out
