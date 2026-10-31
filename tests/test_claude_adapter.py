"""Claude Code adapter: hook translation, launch spec, profiles, locators, and the real hook script
talking to a live host agent."""

import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from conftest import run_hook, wait_for

from sessionorc.adapters import short_model
from sessionorc.client import LocalClient
from sessionorc.models import Session
from shiftlead import profiles
from shiftlead.adapters.claude_code import (
    AT_COMPOSER_ENV,
    CADENCE_HOOK_LINE,
    HOOK_EVENTS,
    ClaudeCodeAdapter,
    _pid_alive,
    context_file,
    context_report,
    global_config_file,
    hooks_settings,
    munge,
    parse_usage,
    pretrust,
    repo_wires_cadence,
    write_hooks_file,
)
from shiftlead.adapters.claude_code.hook import call_sig, translate

CAPTURED = Path(__file__).parent / "conformance/fixtures/claude-code/captured"

pytestmark = pytest.mark.integration  # the hook-script tests spawn processes; split later if wanted

# -- pure -------------------------------------------------------------------------------------


def test_translate_state_events():
    assert translate({"hook_event_name": "SessionStart", "session_id": "u1"}) == {
        "adapter_id": "u1",
        "state": "working",
        "pending": None,
        "subagents_reset": True,
    }
    assert translate({"hook_event_name": "Stop"})["state"] == "idle"
    assert translate({"hook_event_name": "SessionEnd", "reason": "prompt_input_exit"})["state"] == "exited"
    assert translate({"hook_event_name": "SessionEnd", "reason": "clear"}) is None  # process still alive
    assert translate({"hook_event_name": "SessionEnd", "reason": "resume"}) is None
    assert translate({"hook_event_name": "PreCompact"}) is None


def test_a_compaction_is_not_a_start():
    """TD-090: a compaction ends in SessionStart(source=compact); a manual `/compact` fires nothing
    after it, so reading it as `working` left an idle session `stalled?` for ever."""
    ev = {"hook_event_name": "SessionStart", "session_id": "u1", "source": "compact"}
    assert translate(ev) == {"adapter_id": "u1"}  # no state: it stays what it was
    # the payload's file is the record's `transcript` (design §4.2, TD-578), on any event with an id
    tp = "/home/k/.claude/projects/-r/u1.jsonl"
    assert translate({**ev, "transcript_path": tp}) == {"adapter_id": "u1", "transcript": tp}
    assert translate({**ev, "model": "claude-opus-5"}) == {"adapter_id": "u1", "model": "claude-opus-5"}
    assert translate({"hook_event_name": "SessionStart", "source": "compact"}) is None
    assert translate({**ev, "source": "startup"})["state"] == "working"


def test_a_resume_lands_at_the_composer():
    """TD-155: `claude --resume` prints the conversation and waits at the composer, and no Stop
    follows, so `working` read `stalled?` at STALL_AFTER and the doorbell never rang it."""
    ev = {"hook_event_name": "SessionStart", "session_id": "u1", "source": "resume"}
    assert translate(ev) == {"adapter_id": "u1", "state": "idle", "pending": None, "subagents_reset": True}
    # a prompt given with the resume is its own turn, reported by UserPromptSubmit after it
    assert translate({"hook_event_name": "UserPromptSubmit", "session_id": "u1"})["state"] == "working"
    assert translate({**ev, "source": "startup"})["state"] == "working"  # `ao new` types its prompt at once


def test_a_clear_lands_at_the_composer():
    """TD-592: `/clear` starts a new conversation in the same process and waits at an empty composer;
    no Stop follows, so `working` sat on the chip until the next turn ended."""
    ev = {"hook_event_name": "SessionStart", "session_id": "u2", "source": "clear"}
    assert translate(ev) == {"adapter_id": "u2", "state": "idle", "pending": None, "subagents_reset": True}
    # the SessionEnd before it says nothing: the process lives on
    assert translate({"hook_event_name": "SessionEnd", "session_id": "u1", "reason": "clear"}) is None


def test_a_launch_with_no_prompt_starts_idle():
    """TD-283: a launch with no prompt (Add entry's **Open a session**, `ao new` without one) lands at
    the composer, and no Stop follows until a turn runs; the launch marks it in the pane's environment
    and its `startup` reads `idle`. A launch with a prompt, a resume and a `/clear` are as before
    (a `/clear` reads `idle` since TD-592)."""
    ev = {"hook_event_name": "SessionStart", "session_id": "u1", "source": "startup"}
    assert translate(ev, at_composer=True) == {
        "adapter_id": "u1",
        "state": "idle",
        "pending": None,
        "subagents_reset": True,
    }
    assert translate(ev)["state"] == "working"
    assert translate({**ev, "source": "clear"}, at_composer=True)["state"] == "idle"
    assert translate({**ev, "source": "compact"}, at_composer=True) == {"adapter_id": "u1"}
    turn = {"hook_event_name": "UserPromptSubmit", "session_id": "u1"}
    assert translate(turn, at_composer=True)["state"] == "working"  # its first turn is a turn


def test_a_subagents_tool_events_leave_the_state_alone():
    """TD-201: the tool sets `agent_id` only on an event from inside a subagent. A background agent
    runs on after its caller's Stop, so its tool events read as `working` held an idle session unrung;
    they carry the session id and no state. The main thread's own tool events name themselves in
    `event`, which the host agent logs when one wakes a hook-confirmed idle session."""
    ev = {"hook_event_name": "PreToolUse", "session_id": "u1", "tool_name": "Bash", "tool_input": {}}
    sig = call_sig(ev)
    assert translate(ev) == {
        "adapter_id": "u1",
        "state": "working",
        "pending": None,
        "event": "PreToolUse:Bash",
        "call": "start",  # TD-950: a call's first event, in the core's words
        "call_sig": sig,
    }
    assert translate({**ev, "hook_event_name": "PostToolUse"})["event"] == "PostToolUse:Bash"
    assert translate({"hook_event_name": "PostToolUse"})["event"] == "PostToolUse"  # no tool name: the event's own
    # and say only that a subagent is alive (TD-734), which the core reads as `subagent_seen` — with its
    # call, which is that subagent's thread's (TD-950), and still no state
    assert translate({**ev, "agent_id": "a97a5f", "tool_use_id": "tu1"}) == {
        "adapter_id": "u1",
        "subagent": "a97a5f",
        "subagent_seen": True,
        "call": "start",
        "tool_use_id": "tu1",
        "call_sig": sig,
    }
    assert translate({"hook_event_name": "PostToolUse", "agent_id": "a97a5f"}) == {
        "subagent": "a97a5f",
        "subagent_seen": True,
        "call": "end",
    }
    assert "event" not in translate({"hook_event_name": "UserPromptSubmit"})  # a turn's start is not named
    # a question asked from inside a subagent still stops the session for the person
    ask = {**ev, "agent_id": "a1", "tool_name": "AskUserQuestion", "tool_input": {"questions": [{"question": "q?"}]}}
    assert translate(ask)["state"] == "needs-you"


def test_translate_permission_and_questions():
    p = translate(
        {
            "hook_event_name": "PermissionRequest",
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin td-301"},
            "tool_use_id": "tu9",
        }
    )
    assert p == {
        "kind": "permission",
        "text": "Bash: git push origin td-301",
        "tool_use_id": "tu9",
        # the tool and its input, for the person's permissions: rules (TD-641)
        "tool": "Bash",
        "input": {"command": "git push origin td-301"},
        "call_sig": call_sig({"tool_name": "Bash", "tool_input": {"command": "git push origin td-301"}}),
    }
    # a question that reaches the PermissionRequest hook is a question, as the PreToolUse road reports
    # it: its text, never its JSON (TD-629), and no permission, so nothing waits on Allow / Deny (TD-674)
    a = translate(
        {
            "hook_event_name": "PermissionRequest",
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": "Which db?", "options": [{"label": "pg"}]}]},
            "tool_use_id": "tu8",
        }
    )
    assert a == {"state": "needs-you", "pending": {"kind": "question", "text": "Which db?"}}
    # a tool event names its call, which ends that call's waiter if its dialog was answered in the terminal
    done = translate({"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_use_id": "tu9"})
    assert done == {
        "state": "working",
        "pending": None,
        "event": "PostToolUse:Bash",
        "call": "end",
        "tool_use_id": "tu9",
    }
    q = translate(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": "Which db?"}]},
        }
    )
    assert q["state"] == "needs-you" and q["pending"] == {"kind": "question", "text": "Which db?"}
    n = translate({"hook_event_name": "Notification", "notification_type": "permission_prompt", "message": "m"})
    assert n["pending"]["kind"] == "question"  # dialog is in the terminal now
    assert n["notice"] == "permission_prompt"  # the dialog's own notice, weighed against an open prompt (TD-950)
    assert translate({"hook_event_name": "Notification", "notification_type": "auth_success"}) is None
    assert translate({"hook_event_name": "Notification", "notification_type": "idle_prompt", "message": "w"}) is None
    assert translate({"hook_event_name": "SubagentStart"}) == {"subagent_delta": 1, "subagent_seen": True}


def test_a_subagents_permission_names_its_subagent_and_its_call():
    """TD-950 (design §4.2 *A subagent's dialog is held back*, *A waiter is keyed by its call*), from the
    captured `subagent-permission/background/`: the subagent's `PermissionRequest` names no call, so it
    carries the subagent's id and name and a `call_sig` equal to its own `PreToolUse`'s, which names the
    call. Every event from inside the subagent carries `subagent`, its `SubagentStart` too."""
    events = [json.loads(line) for line in (CAPTURED / "subagent-permission/background/hooks.jsonl").open()]
    asked = next(e for e in events if e["hook_event_name"] == "PermissionRequest")
    pre = next(e for e in events if e["hook_event_name"] == "PreToolUse" and e.get("agent_id") == asked["agent_id"])
    p, t = translate(asked), translate(pre)
    assert p["kind"] == "permission" and p["tool_use_id"] is None
    assert (p["subagent"], p["subagent_name"]) == (asked["agent_id"], "general-purpose")
    assert p["call_sig"] == t["call_sig"] and t["tool_use_id"] == pre["tool_use_id"]
    assert (t["subagent"], t["call"]) == (asked["agent_id"], "start") and "state" not in t
    start = next(e for e in events if e["hook_event_name"] == "SubagentStart")
    assert translate(start)["subagent"] == start["agent_id"]
    # a main-thread prompt names no subagent; a subagent with no type is shown as one
    assert "subagent_name" not in translate({**asked, "agent_id": None})
    assert translate({**asked, "agent_type": None})["subagent_name"] == "subagent"


def test_a_fresh_conversation_resets_the_subagent_count():
    """TD-734 (§4.2 *Working on its own*): a SessionStart of source `startup` — at the composer or with a
    brief — `resume` or `clear` carries `subagents_reset`, since no subagent of the old conversation is
    alive; a `compact` keeps the conversation and its count. Start and Stop carry `subagent_seen`."""
    ev = {"hook_event_name": "SessionStart", "session_id": "u1"}
    for source in ("startup", "resume", "clear"):
        assert translate({**ev, "source": source})["subagents_reset"] is True, source
    assert translate({**ev, "source": "startup"}, at_composer=True)["subagents_reset"] is True
    assert "subagents_reset" not in translate({**ev, "source": "compact"})
    assert translate({"hook_event_name": "SubagentStop"}) == {"subagent_delta": -1, "subagent_seen": True}
    assert "subagent_seen" not in translate({"hook_event_name": "Stop"})


def test_hooks_settings_shape():
    prof = profiles.Profile(name="p", permission_wait=120)
    h = hooks_settings(prof, "/x/shiftlead-hook")["hooks"]
    assert set(h) >= {"PermissionRequest", "Stop", "Notification", "SessionEnd", "SubagentStop"}
    pr = h["PermissionRequest"][0]["hooks"][0]
    assert pr["command"] == "/x/shiftlead-hook" and pr["timeout"] == 135
    assert h["Stop"][0]["hooks"][0]["timeout"] == 10
    assert len(h["SessionStart"][0]["hooks"]) == 1  # no cadence line unless asked
    hc = hooks_settings(prof, "/x/shiftlead-hook", cadence_line=True)["hooks"]
    ss = hc["SessionStart"][0]["hooks"]
    assert [x["command"] for x in ss] == ["/x/shiftlead-hook", CADENCE_HOOK_LINE] and ss[1]["timeout"] >= 130
    # The line reads the main checkout (dev-cadence TD-055 (b), 2026-09-25): the first entry of
    # `git worktree list --porcelain`, falling back to the directory's own copy outside a git repo; its
    # pinned and copied modes are tests/test_cadence_hook_line.py's (TD-1023).
    assert CADENCE_HOOK_LINE.startswith('r=$(git -C "${CLAUDE_PROJECT_DIR:-.}" worktree list --porcelain')
    assert 'elif [ -x "$f" ]; then "$f" --session-start; fi' in CADENCE_HOOK_LINE
    assert len(hc["Stop"][0]["hooks"]) == 1  # only SessionStart gains it


def _settings(d: Path, commands: list[str]) -> None:
    (d / ".claude").mkdir(parents=True, exist_ok=True)
    hooks = [{"type": "command", "command": c, "timeout": 20} for c in commands]
    (d / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": hooks}]}}))


def test_repo_wires_cadence_and_layer_choice(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    prof = profiles.Profile(name="p")
    bare = tmp_path / "bare"  # no settings at all: a plain directory, or a repo that is no consumer
    bare.mkdir()
    assert repo_wires_cadence(bare) is False
    runner = tmp_path / "runner"  # post-2026-09-11: the one line
    _settings(
        runner, ['f="$CLAUDE_PROJECT_DIR/scripts/cadence_hooks.sh"; if [ -x "$f" ]; then "$f" --session-start; fi']
    )
    assert repo_wires_cadence(runner) is True
    legacy = tmp_path / "legacy"  # the pre-migration per-hook block, recognised by its attention line
    _settings(
        legacy,
        [
            '"$CLAUDE_PROJECT_DIR/scripts/check_anchor.py" --hook',
            '"$CLAUDE_PROJECT_DIR/scripts/nudge_user_attention.py" --report --due-only',
        ],
    )
    assert repo_wires_cadence(legacy) is True
    other = tmp_path / "other"  # SessionStart hooks of its own, none of them agent-cadence's
    _settings(other, ["echo hi"])
    assert repo_wires_cadence(other) is False
    broken = tmp_path / "broken"
    (broken / ".claude").mkdir(parents=True)
    (broken / ".claude" / "settings.json").write_text("{not json")
    assert repo_wires_cadence(broken) is False
    (broken / ".claude" / "settings.json").write_text('{"hooks": {"SessionStart": "oops"}}')
    assert repo_wires_cadence(broken) is False

    # the layer file follows the choice, by name, so two launches into different dirs do not collide
    plain = write_hooks_file(prof, runner)
    plus = write_hooks_file(prof, bare)
    assert plain.name == "p.json" and plus.name == "p+cadence.json"
    assert len(json.loads(plain.read_text())["hooks"]["SessionStart"][0]["hooks"]) == 1
    assert json.loads(plus.read_text())["hooks"]["SessionStart"][0]["hooks"][1]["command"] == CADENCE_HOOK_LINE
    assert write_hooks_file(prof).name == "p.json"  # no cwd: the plain layer, as before


def test_an_unattended_layer_refuses_the_tools_peer_messages(tmp_path, monkeypatch):
    """TD-064 (a), design §4.10 *The tool's own peer channel*: Claude Code's default holds a message
    from a session in another permission-mode class behind a deliver-or-deny panel no hook reports,
    so an unattended launch refuses them in its layer; an interactive one keeps the tool's default,
    and the two are separate files so concurrent launches never overwrite each other's."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    prof = profiles.Profile(name="p")
    assert "crossSessionInbound" not in hooks_settings(prof)
    assert hooks_settings(prof, unattended=True)["crossSessionInbound"] == "refuse"
    # nobody reads a suggested next prompt at an unattended pane (TD-201); a person's session keeps them
    assert hooks_settings(prof, unattended=True)["promptSuggestionEnabled"] is False
    assert "promptSuggestionEnabled" not in hooks_settings(prof)
    bare = tmp_path / "bare"
    bare.mkdir()
    att, un = write_hooks_file(prof, bare), write_hooks_file(prof, bare, unattended=True)
    assert (att.name, un.name) == ("p+cadence.json", "p+cadence+unattended.json")
    assert "crossSessionInbound" not in json.loads(att.read_text())
    assert json.loads(un.read_text())["crossSessionInbound"] == "refuse"
    assert write_hooks_file(prof, unattended=True).name == "p+unattended.json"


def test_the_hook_command_falls_back_to_the_one_beside_the_interpreter(tmp_path, monkeypatch):
    """TD-301: a container node's host agent runs from its venv with that venv off PATH, so the layer
    names the `shiftlead-hook` beside `sys.executable` rather than a bare name no session resolves."""
    from shiftlead.adapters import claude_code as cc

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    venv = tmp_path / "venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("")
    hook = venv / "shiftlead-hook"
    hook.write_text("#!/bin/sh\n")
    hook.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(cc.sys, "executable", str(venv / "python"))
    assert cc.hook_command() == str(hook)
    layer = json.loads(write_hooks_file(profiles.Profile(name="p")).read_text())
    assert layer["hooks"]["SessionStart"][0]["hooks"][0]["command"] == str(hook)
    hook.unlink()  # neither on PATH nor beside: the bare name, with the warning, as before
    assert cc.hook_command() is None


def test_a_metered_profiles_launch_pins_the_prompt_cache_to_an_hour(tmp_path, monkeypatch):
    """§4.2a *A metered profile's prompt cache lives an hour* (TD-470): `1h` on a metered profile's
    launch, nothing on a subscription's, and the host agent's own key passed for either billing; the
    subagents' key is left to the tool."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CLAUDE_CODE_PROMPT_CACHE_TTL", raising=False)
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "profiles.yml").write_text(
        "default: paul\nprofiles:\n  paul: {account: paul, config_dir: ~/.claude}\n"
        "  api: {account: key, billing: metered, config_dir: /tmp/cc-api}\n"
    )
    ad = ClaudeCodeAdapter(binary="claude")

    def env(profile: str) -> dict:
        return ad.launch(profile=profile, resume=None, prompt=None, unattended=True, cwd=tmp_path).env

    assert env("api")["CLAUDE_CODE_PROMPT_CACHE_TTL"] == "1h"
    assert "CLAUDE_CODE_PROMPT_CACHE_TTL" not in env("paul")
    assert not any("SUBAGENT" in k for k in env("api"))
    monkeypatch.setenv("CLAUDE_CODE_PROMPT_CACHE_TTL", "5m")  # the person's word, for either billing
    assert env("api")["CLAUDE_CODE_PROMPT_CACHE_TTL"] == "5m"
    assert env("paul")["CLAUDE_CODE_PROMPT_CACHE_TTL"] == "5m"


def test_launch_argv_and_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "profiles.yml").write_text(
        "default: paul\nprofiles:\n  paul: {account: paul, model: opus, config_dir: ~/.claude}\n"
        "  grind: {account: grind, model: sonnet, config_dir: /tmp/cc-grind, permission_wait: 30}\n"
    )
    ad = ClaudeCodeAdapter(binary="claude")
    spec = ad.launch(profile="", resume=None, prompt="do it", unattended=False, cwd=tmp_path, name="t1")
    assert spec.argv[0] == "claude" and "--settings" in spec.argv and "--session-id" in spec.argv
    assert spec.adapter_id and uuid.UUID(spec.adapter_id)
    assert spec.first_prompt == "do it" and "--model" in spec.argv and "--name" in spec.argv
    assert spec.model == "opus"  # the profile's alias, the host's `AGENT_MODEL` (§4.2, TD-644)
    assert not any("do it" in a for a in spec.argv)  # typed at the composer, never passed (TD-339)
    assert "CLAUDE_CONFIG_DIR" not in spec.env or spec.env["CLAUDE_CONFIG_DIR"].endswith(".claude")
    assert spec.env["SHIFTLEAD_PERMISSION_WAIT"] == "600"
    assert "SHIFTLEAD_PROFILE" not in spec.env  # read by nothing (TD-149 (8)); the record carries the profile
    assert spec.env[AT_COMPOSER_ENV] == "1"  # every launch lands at the composer, its brief typed there (TD-339)
    bare = ad.launch(profile="", resume=None, prompt=None, unattended=False, cwd=tmp_path)
    assert bare.env[AT_COMPOSER_ENV] == "1"
    hooks_path = Path(spec.argv[spec.argv.index("--settings") + 1])
    assert json.loads(hooks_path.read_text())["hooks"]["Stop"]

    g = ad.launch(profile="grind", resume="abc-123", prompt=None, unattended=True, cwd=tmp_path)
    assert g.adapter_id == "abc-123" and "--resume" in g.argv and "--session-id" not in g.argv
    assert "--dangerously-skip-permissions" in g.argv
    assert g.env["CLAUDE_CONFIG_DIR"] == "/tmp/cc-grind" and g.env["SHIFTLEAD_PERMISSION_WAIT"] == "30"
    assert AT_COMPOSER_ENV not in g.env  # a resume's own `source: resume` says it
    # the unattended launch carries the refusing layer, the interactive one does not (TD-064 (a))
    g_layer = json.loads(Path(g.argv[g.argv.index("--settings") + 1]).read_text())
    assert g_layer["crossSessionInbound"] == "refuse"
    assert "crossSessionInbound" not in json.loads(hooks_path.read_text())
    dashed = ad.launch(profile="", resume=None, prompt="-1 is the answer", unattended=False, cwd=tmp_path)
    assert dashed.first_prompt == "-1 is the answer" and "--" not in dashed.argv
    with pytest.raises(KeyError, match="unknown profile"):
        ad.launch(profile="nope", resume=None, prompt=None, unattended=False, cwd=tmp_path)
    # the account a profile runs under, for the once-per-account usage poll (§4.2a, TD-122)
    assert (ad.account_for("grind"), ad.account_for(""), ad.account_for("nope")) == ("grind", "paul", None)
    assert ad.label == "Claude"


def test_pretrust_writes_once_and_keeps_other_state(tmp_path):
    prof = profiles.Profile(name="t", config_dir=tmp_path)
    cfg = tmp_path / ".claude.json"
    cfg.write_text(json.dumps({"oauthAccount": {"x": 1}, "projects": {"/other": {"hasTrustDialogAccepted": True}}}))
    assert pretrust(tmp_path / "repo", prof) is True
    d = json.loads(cfg.read_text())
    assert d["oauthAccount"] == {"x": 1} and d["projects"]["/other"]["hasTrustDialogAccepted"] is True
    assert d["projects"][str(tmp_path / "repo")]["hasTrustDialogAccepted"] is True
    assert pretrust(tmp_path / "repo", prof) is False  # already trusted: no write
    assert oct(cfg.stat().st_mode & 0o777) == "0o600"


def test_claude_json_lives_in_the_config_dir(tmp_path, monkeypatch):
    # Verified 2026-10-08 against Claude Code 2.1.295 (TD-006): with CLAUDE_CONFIG_DIR set, a first run
    # writes `.claude.json` inside that directory, not beside it as `~/.claude.json` is beside `~/.claude`.
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert global_config_file(profiles.Profile(name="t", config_dir=tmp_path)) == tmp_path / ".claude.json"
    assert global_config_file(profiles.Profile(name="t")) == Path("~/.claude.json").expanduser()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "env"))
    assert global_config_file(profiles.Profile(name="t")) == tmp_path / "env" / ".claude.json"


def test_profiles_default_when_missing(tmp_path):
    p, d = profiles.load(tmp_path / "none.yml")
    assert d == "default" and p["default"].config_dir is None
    bad = tmp_path / "bad.yml"
    bad.write_text("default: x\nprofiles:\n  y: {}\n")
    with pytest.raises(ValueError, match="not a declared profile"):
        profiles.load(bad)


def test_munge_and_transcript_path(tmp_path):
    assert munge("/home/p/work_history") == "-home-p-work-history"
    prof = profiles.Profile(name="t", config_dir=tmp_path)
    d = tmp_path / "projects" / munge(tmp_path / "repo")
    d.mkdir(parents=True)
    (d / "abc.jsonl").write_text("{}\n")
    ad = ClaudeCodeAdapter()
    assert ad.transcript_path("abc", tmp_path / "repo", prof) == d / "abc.jsonl"
    assert ad.transcript_path("zzz", tmp_path / "repo", prof) is None


def test_translate_carries_the_model_when_the_payload_has_one():
    """TD-031: only SessionStart carries `model`, and not always; a `/model` mid-session reports
    itself as PostModelSwitch's `to_model`. Every other event says nothing about the model."""
    assert translate({"hook_event_name": "SessionStart", "session_id": "u1", "model": "claude-opus-5"}) == {
        "adapter_id": "u1",
        "model": "claude-opus-5",
        "state": "working",
        "pending": None,
        "subagents_reset": True,
    }
    assert "model" not in translate({"hook_event_name": "SessionStart", "session_id": "u1"})
    assert "model" not in translate({"hook_event_name": "Stop"})
    switch = translate({"hook_event_name": "PostModelSwitch", "from_model": "claude-opus-5", "to_model": "x-1"})
    assert switch == {"model": "x-1"} and "state" not in switch  # a switch is not a state change
    assert translate({"hook_event_name": "PostModelSwitch"}) is None  # nothing to report
    assert "PostModelSwitch" in HOOK_EVENTS  # or the switch never reaches the hook at all


def test_model_in_use_reads_the_last_top_level_assistant_turn(tmp_path, monkeypatch):
    """TD-031: the transcript entry's own `message.model`, never a grep, and never a sidechain
    entry — a subagent's model is not the session's."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "profiles.yml").write_text(
        f"default: t\nprofiles:\n  t: {{account: t, model: opus, config_dir: {tmp_path / 'cc'}}}\n"
    )
    ad = ClaudeCodeAdapter()
    assert ad.model_in_use("abc", tmp_path / "repo", "t") is None  # no transcript at all: not an error
    d = tmp_path / "cc" / "projects" / munge(tmp_path / "repo")
    d.mkdir(parents=True)
    entries = [
        {"type": "assistant", "message": {"model": "claude-opus-5"}},
        # an Agent call that *requests* a subagent model: a grep for "model" would read this one
        {"type": "user", "message": {"content": [{"tool_use": {"input": {"model": "sonnet"}}}]}},
        {"type": "assistant", "message": {"model": "claude-fable-5-1"}},
        {"type": "assistant", "isSidechain": True, "message": {"model": "claude-haiku-4-5"}},
        {"type": "system", "message": {"model": "<synthetic>"}},
    ]
    (d / "abc.jsonl").write_text("".join(json.dumps(e) + "\n" for e in entries))
    assert ad.model_in_use("abc", tmp_path / "repo", "t") == "claude-fable-5-1"
    assert ad.model_in_use("abc", tmp_path / "repo") == "claude-fable-5-1"  # the default profile is this one
    assert ad.model_in_use("abc", tmp_path / "repo", "nope") is None  # an unknown profile, not an exception
    # a truncated first line (the tail is read from the end, not the start) is skipped, not fatal
    (d / "abc.jsonl").write_text('del": "fragment"}\n' + json.dumps(entries[0]) + "\n")
    assert ad.model_in_use("abc", tmp_path / "repo", "t") == "claude-opus-5"
    assert short_model("claude-code", "claude-fable-5-1") == "fable-5-1"
    assert short_model("shell", "claude-fable-5-1") == "claude-fable-5-1"  # an adapter with no opinion
    assert short_model("claude-code", None) == ""


def test_context_reads_the_last_top_level_turns_usage(tmp_path, monkeypatch):
    """TD-190, design §4.3 `context`: the prompt the last top-level turn sent — input plus both
    cache counts — stamped with that turn's time, and the model's window where the table knows it.
    A sidechain turn is a subagent's, and a cut first line is skipped."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "profiles.yml").write_text(
        f"default: t\nprofiles:\n  t: {{account: t, model: opus, config_dir: {tmp_path / 'cc'}}}\n"
    )
    ad = ClaudeCodeAdapter()
    repo = tmp_path / "repo"
    assert ad.context("abc", repo, "t") is None  # no transcript: cannot tell, never an error
    d = tmp_path / "cc" / "projects" / munge(repo)
    d.mkdir(parents=True)
    use = {"input_tokens": 3, "cache_read_input_tokens": 230_000, "cache_creation_input_tokens": 1_200}
    entries = [
        {"type": "assistant", "timestamp": "T1", "message": {"model": "claude-opus-5-5", "usage": {"input_tokens": 9}}},
        {"type": "assistant", "timestamp": "T2", "message": {"model": "claude-opus-5-5", "usage": use}},
        {
            "type": "assistant",
            "isSidechain": True,
            "timestamp": "T3",
            "message": {"model": "claude-sonnet-5", "usage": use},
        },
        {"type": "assistant", "timestamp": "T4", "message": {"model": "<synthetic>", "usage": {"input_tokens": 0}}},
    ]
    (d / "abc.jsonl").write_text("".join(json.dumps(e) + "\n" for e in entries))
    assert ad.context("abc", repo, "t") == {"tokens": 231_203, "at": "T2", "window": 1_000_000}
    assert ad.context("abc", repo, "nope") is None  # an unknown profile, not another account's files
    # a model the table does not know: the tokens alone
    other = {"type": "assistant", "timestamp": "T5", "message": {"model": "claude-x-1", "usage": use}}
    (d / "abc.jsonl").write_text('del": "cut"}\n' + json.dumps(other) + "\n")
    assert ad.context("abc", repo, "t") == {"tokens": 231_203, "at": "T5", "window": None}
    haiku = {"type": "assistant", "message": {"model": "claude-haiku-4-5", "usage": use}}
    (d / "abc.jsonl").write_text(json.dumps(haiku) + "\n")
    assert ad.context("abc", repo, "t")["window"] == 200_000


def test_context_prefers_the_window_the_status_line_reported(tmp_path, monkeypatch):
    """TD-295, design §4.3 `context`: a window the session's status line reported beats the table's —
    a reported 200k on a model the table gives 1M — and its tokens win only when they are later
    than the transcript's last turn; with no turn yet, the report alone is the reading."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "profiles.yml").write_text(
        f"default: t\nprofiles:\n  t: {{account: t, model: opus, config_dir: {tmp_path / 'cc'}}}\n"
    )
    ad = ClaudeCodeAdapter()
    repo = tmp_path / "repo"
    rep = context_file("abc")
    rep.parent.mkdir(parents=True)
    rep.write_text(json.dumps({"window": 200_000, "tokens": 150_000, "at": "2026-10-03T12:00:00.000Z"}))
    assert ad.context("abc", repo, "t") == {"tokens": 150_000, "at": "2026-10-03T12:00:00.000Z", "window": 200_000}
    d = tmp_path / "cc" / "projects" / munge(repo)
    d.mkdir(parents=True)
    use = {"input_tokens": 3, "cache_read_input_tokens": 230_000, "cache_creation_input_tokens": 1_200}
    turn = {
        "type": "assistant",
        "timestamp": "2026-10-03T12:05:00.000Z",
        "message": {"model": "claude-opus-5-5", "usage": use},
    }
    (d / "abc.jsonl").write_text(json.dumps(turn) + "\n")
    # the turn is later than the report: its tokens, the report's window
    assert ad.context("abc", repo, "t") == {"tokens": 231_203, "at": "2026-10-03T12:05:00.000Z", "window": 200_000}
    rep.write_text(json.dumps({"window": 200_000, "tokens": 240_000, "at": "2026-10-03T12:06:00.000Z"}))
    assert ad.context("abc", repo, "t") == {"tokens": 240_000, "at": "2026-10-03T12:06:00.000Z", "window": 200_000}
    rep.write_text("not json")  # a broken report: the table again
    assert ad.context("abc", repo, "t")["window"] == 1_000_000
    sonnet46 = {**turn, "message": {"model": "claude-sonnet-4-6", "usage": use}}
    (d / "abc.jsonl").write_text(json.dumps(sonnet46) + "\n")
    assert ad.context("abc", repo, "t")["window"] == 200_000  # 1M only through `[1m]`, which the id hides


def test_context_report_reads_the_status_lines_window():
    cw = {
        "context_window_size": 200_000,
        "used_percentage": 42,
        "current_usage": {
            "input_tokens": 8,
            "output_tokens": 500,
            "cache_creation_input_tokens": 2_000,
            "cache_read_input_tokens": 80_000,
        },
    }
    assert context_report({"session_id": "u1", "context_window": cw}) == {
        "sid": "u1",
        "window": 200_000,
        "tokens": 82_008,
    }
    # before the first response the tool sends no usage: the window alone
    fresh = {"session_id": "u1", "context_window": {**cw, "current_usage": None}}
    assert context_report(fresh) == {"sid": "u1", "window": 200_000, "tokens": None}
    assert context_report({"session_id": "u1"}) is None  # an old client names no window
    assert context_report({"context_window": cw}) is None  # nor is one kept with no session to key it
    assert context_report("x") is None


def test_parse_usage_and_credentials(tmp_path):
    u = parse_usage(
        {"five_hour": {"utilization": 42.7, "resets_at": "2026-09-07T02:00:00Z"}, "seven_day": {"utilization": 9}}
    )
    # TD-073: the endpoint's two windows become two labelled entries of a list; nothing above the
    # adapter knows what `5h` and `week` are, and a tool with other windows says what it has instead.
    assert u and [(w.label, w.pct) for w in u.windows] == [("5h", 42), ("week", 9)]
    assert u.windows[0].resets.startswith("2026") and u.windows[1].resets is None
    assert parse_usage({}) is None
    # TD-122: a per-model weekly window beside *All models* is carried, labelled by the model; an
    # empty one, and a `seven_day_*` key that is not a model, are not windows
    u = parse_usage(
        {
            "five_hour": {"utilization": 7, "resets_at": None},
            "seven_day": {"utilization": 24, "resets_at": None},
            "seven_day_fable": {"utilization": 17.4, "resets_at": "2026-09-30T00:00:00Z"},
            "seven_day_opus": None,
            "seven_day_sonnet": {"utilization": None},
            "seven_day_oauth_apps": {"utilization": 3},
        }
    )
    assert u and [(w.label, w.pct) for w in u.windows] == [("5h", 7), ("week", 24), ("week · Fable", 17)]
    prof = profiles.Profile(name="t", config_dir=tmp_path)
    ad = ClaudeCodeAdapter()
    assert ad.credentials_ok(prof) is None
    (tmp_path / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": "x", "expiresAt": 1}}))
    assert ad.credentials_ok(prof) is False
    (tmp_path / ".credentials.json").write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "x", "refreshTokenExpiresAt": 4102444800000}})
    )
    assert ad.credentials_ok(prof) is True


# -- the real hook script against a live agent ---------------------------------------------------


async def test_hook_script_end_to_end(agent, hookstub, tmp_path):
    async with LocalClient() as c:
        s = await c.call("create", name="h", dir=str(tmp_path), adapter=hookstub.name)
        sid = s["id"]
        # Stop → idle, carrying the Claude session id
        cp = await asyncio.to_thread(run_hook, sid, {"hook_event_name": "Stop", "session_id": "cc-uuid"})
        assert cp.returncode == 0 and cp.stdout == ""
        x = await c.call("get", id=sid)
        assert x["adapter_id"] == "cc-uuid"
        # PermissionRequest blocks; Allow from the UI prints the decision JSON
        payload = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "Bash",
            "tool_input": {"command": "git push"},
            "tool_use_id": "tu-e2e",
        }
        fut = asyncio.get_running_loop().run_in_executor(None, run_hook, sid, payload)

        async def needs_you():
            return (await c.call("get", id=sid))["state"] == "needs-you"

        assert await wait_for(needs_you)
        x = await c.call("get", id=sid)
        assert x["pending"]["kind"] == "permission" and x["pending"]["text"] == "Bash: git push"
        await c.call("decide", id=sid, tool_use_id="tu-e2e", behavior="deny", reason="not yet")
        cp = await fut
        out = json.loads(cp.stdout)
        assert out["hookSpecificOutput"]["decision"] == {"behavior": "deny", "reason": "not yet"}
        # timeout → no output, session pending becomes a terminal question
        cp = await asyncio.to_thread(run_hook, sid, {**payload, "tool_use_id": "tu-late"}, "0.3")
        assert cp.returncode == 0 and cp.stdout == ""
        x = await c.call("get", id=sid)
        assert x["pending"]["kind"] == "question"


async def test_a_question_at_the_permission_hook_waits_on_nothing(agent, hookstub, tmp_path):
    """TD-674, design §4.2: an `AskUserQuestion` that reaches the `PermissionRequest` hook was drawn as a
    permission — Allow / Deny on the card, Focus, the Inbox row and the team's facet, which cannot pick
    one of its options. The hook now returns at once with no decision, the record is `needs-you` with
    a `question` pending and no waiter, and every surface built from it draws its text and Focus."""
    from shiftlead.ui import org
    from shiftlead.ui.app import state_rows, templates, view

    async with LocalClient() as c:
        sid = (await c.call("create", name="q", dir=str(tmp_path), adapter=hookstub.name))["id"]
        payload = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": "Press does?", "options": [{"label": "one"}, {"label": "two"}]}]},
            "tool_use_id": "tu-ask",
        }
        cp = await asyncio.to_thread(run_hook, sid, payload, "20")  # a permission would block for 20 s
        assert cp.returncode == 0 and cp.stdout == ""  # no decision: the terminal's menu answers it
        rec = await c.call("get", id=sid)
        assert rec["state"] == "needs-you" and rec["pending"]["kind"] == "question"
        assert rec["pending"]["text"] == "Press does?" and not rec["pending"].get("tool_use_id")
        assert not agent._permission_waiting(sid)
    v = view(rec, [rec])
    assert v["next_act"] != "allow" and v["slot"]["text"] == "question: Press does?"
    html = templates.get_template("inbox_rows.html").render(rows=state_rows([v]), section="needs")
    assert "Press does?" in html and ">Open<" in html and 'data-act="allow"' not in html
    assert [(a["kind"], a["text"]) for a in org.answer_blocks([rec])] == [("question", "Press does?")]


def _captured(name: str) -> list[dict]:
    """A capture's hook events in order, through `translate()`, each with its payload as `raw`."""
    out = []
    for line in (CAPTURED / f"subagent-permission/{name}/hooks.jsonl").open():
        raw = json.loads(line)
        if (ev := translate(raw)) is not None:
            out.append({**ev, "raw": raw})
    return out


async def _feed(agent, c, sid, events, wait=10):
    """Each event to the host agent as the hook script sends it; a permission blocks, so it runs as a
    task, returned once its waiter is registered."""
    task = None
    for e in events:
        ev = {k: v for k, v in e.items() if k != "raw"}
        if ev.get("kind") == "permission":
            n = len(agent._waiters)

            async def ask(ev=ev):
                async with LocalClient() as h:
                    return await h.call("hook", session=sid, wait_seconds=wait, **ev)

            task = asyncio.create_task(ask())

            async def registered(n=n):
                return len(agent._waiters) > n

            assert await wait_for(registered)
        else:
            async with LocalClient() as h:
                await h.call("hook", session=sid, **ev)
    return task


async def test_a_subagents_waiter_is_keyed_by_its_call_and_ended_only_by_its_own_thread(agent, hookstub, tmp_path):
    """TD-950, design §4.2 *A waiter is keyed by its call* and *The thread scopes it*, from the captured
    `subagent-permission/foreground/`: the subagent's permission, which names no call, is keyed by its
    own `PreToolUse`'s `tool_use_id`, and its pending says the pane shows nothing for it. The main
    thread's `Stop` a second later, the dialog's notice and an unknown subagent's tool event end
    nothing — the record stays `needs-you` with its buttons — and **Allow** still answers the hook. In
    place of the Allow, the subagent's event for another call ends nothing, and the asked call's own
    `PostToolUse` ends it as answered in the terminal."""
    events = _captured("foreground")
    i = next(n for n, e in enumerate(events) if e.get("kind") == "permission")
    asked = events[i]
    pre = next(e for e in events[:i] if e.get("call") == "start" and e.get("subagent") == asked["subagent"])
    tid = pre["tool_use_id"]
    async with LocalClient() as c:
        sid = (await c.call("create", name="f", dir=str(tmp_path), adapter=hookstub.name))["id"]
        task = await _feed(agent, c, sid, events[: i + 1])
        assert agent._waiters[(sid, tid)][1] == asked["subagent"]
        rec = await c.call("get", id=sid)
        assert rec["state"] == "needs-you" and rec["pending"]["tool_use_id"] == tid
        assert rec["pending"]["pane_held"] is True and rec["pending"]["subagent_name"] == "general-purpose"
        rest = events[i + 1 :]
        assert [e["raw"]["hook_event_name"] for e in rest] == ["Stop", "Notification", "PreToolUse"]
        assert rest[2]["subagent"] != asked["subagent"]  # the tool's own id, which had no SubagentStart
        await _feed(agent, c, sid, rest)
        assert not task.done() and agent._permission_waiting(sid, asked["subagent"])
        rec = await c.call("get", id=sid)
        assert rec["state"] == "needs-you" and rec["pending"]["kind"] == "permission"
        # an event from inside the subagent ends no main-thread waiter, nor the main thread's its
        assert not agent._permission_waiting(sid, None)
        await c.call("decide", id=sid, tool_use_id=tid, behavior="allow", reason="ok")
        assert await task == {"behavior": "allow", "reason": "ok"}

        # the same prompt again, answered in the terminal this time
        task = await _feed(agent, c, sid, [pre, asked])
        own = {"subagent": asked["subagent"], "subagent_seen": True}
        await _feed(agent, c, sid, [{**own, "call": "end", "tool_use_id": "toolu_other"}, rest[0]])
        assert not task.done()
        await _feed(agent, c, sid, [{**own, "call": "end", "tool_use_id": tid}])
        assert await task is None and not agent._permission_waiting(sid)


async def test_the_tools_own_subagent_stop_moves_no_count_and_ends_no_waiter(agent, hookstub, tmp_path):
    """TD-960, design §4.2 *The thread scopes it*, from the captured `subagent-permission/stray-stop/`: a
    `SubagentStop` for an id no `SubagentStart` named — the tool's own, thirty seconds into the wait —
    leaves `subagents` at 1, the subagent's waiter live and the record `needs-you`; the asked call's own
    `PostToolUse` ends the waiter, and the subagent's own `SubagentStop` takes the count to 0."""
    events = _captured("stray-stop")
    i = next(n for n, e in enumerate(events) if e.get("kind") == "permission")
    asked = events[i]
    started = {e["subagent"] for e in events if (e.get("subagent_delta") or 0) > 0}
    assert asked["subagent"] in started
    j = next(n for n, e in enumerate(events) if (e.get("subagent_delta") or 0) < 0)
    stray = events[j]
    assert j > i and stray["subagent"] not in started
    async with LocalClient() as c:
        sid = (await c.call("create", name="s", dir=str(tmp_path), adapter=hookstub.name))["id"]
        task = await _feed(agent, c, sid, events[: i + 1])
        await _feed(agent, c, sid, events[i + 1 : j + 2])  # the stray stop, then the dialog's notice
        assert events[j + 1].get("notice") == "permission_prompt"
        assert not task.done() and agent._permission_waiting(sid, asked["subagent"])
        rec = await c.call("get", id=sid)
        assert rec["state"] == "needs-you" and rec["pending"]["subagent_name"] == "general-purpose"
        assert rec["subagents"] == 1 and rec["subagent_ids"] == [asked["subagent"]]
        k = next(n for n, e in enumerate(events) if n > j and e.get("call") == "end")
        await _feed(agent, c, sid, events[j + 2 : k + 1])
        assert await task is None and not agent._permission_waiting(sid)
        own = next(e for e in events[k:] if (e.get("subagent_delta") or 0) < 0)
        assert own["subagent"] == asked["subagent"]
        await _feed(agent, c, sid, [own])
        rec = await c.call("get", id=sid)
        assert rec["subagents"] == 0 and rec["subagent_ids"] == []


async def test_an_unannounced_subagent_stop_still_takes_down_a_count_with_no_id(agent, hookstub, tmp_path):
    """TD-960: a count above the record's ids — an id-less start, or a record of an older build — is still
    taken down by a `SubagentStop` whatever its id, and one naming no subagent moves the count as before."""
    async with LocalClient() as c:
        sid = (await c.call("create", name="n", dir=str(tmp_path), adapter=hookstub.name))["id"]
        await c.call("hook", session=sid, subagent_delta=1, subagent_seen=True)  # an id-less start
        await c.call("hook", session=sid, subagent="a1", subagent_delta=1, subagent_seen=True)
        assert (await c.call("get", id=sid))["subagents"] == 2
        await c.call("hook", session=sid, subagent="zz", subagent_delta=-1, subagent_seen=True)
        rec = await c.call("get", id=sid)
        assert rec["subagents"] == 1 and rec["subagent_ids"] == ["a1"]
        await c.call("hook", session=sid, subagent="zz", subagent_delta=-1, subagent_seen=True)
        assert (await c.call("get", id=sid))["subagents"] == 1  # the tool's own: nothing left unnamed
        await c.call("hook", session=sid, subagent_delta=-1, subagent_seen=True)
        assert (await c.call("get", id=sid))["subagents"] == 0


async def test_a_fresh_conversation_forgets_the_subagent_ids(agent, hookstub, tmp_path):
    """TD-961: a `subagents_reset` (a `resume`'s or a `/clear`'s) clears `subagent_ids` with the count, so a
    new subagent that reuses an old conversation's id is counted rather than read as one already running."""
    async with LocalClient() as c:
        sid = (await c.call("create", name="r", dir=str(tmp_path), adapter=hookstub.name))["id"]
        await c.call("hook", session=sid, subagent="a1", subagent_delta=1, subagent_seen=True)
        await c.call("hook", session=sid, subagents_reset=True)
        rec = await c.call("get", id=sid)
        assert rec["subagents"] == 0 and rec["subagent_ids"] == []
        await c.call("hook", session=sid, subagent="a1", subagent_delta=1, subagent_seen=True)
        rec = await c.call("get", id=sid)
        assert rec["subagents"] == 1 and rec["subagent_ids"] == ["a1"]


def test_a_task_stop_names_the_task_it_stopped():
    """TD-1280, design §4.2's `SubagentStart`, `SubagentStop` row: a `PostToolUse` of `TaskStop`, on either
    thread, carries `subagent_stopped` — its `task_id`, else its `shell_id`, a non-empty string — with no
    `subagent_seen` of its own; anything else adds nothing."""

    def stop(tool_input, **kw):
        return {"hook_event_name": "PostToolUse", "tool_name": "TaskStop", "tool_input": tool_input, **kw}

    main = translate(stop({"task_id": "a1"}, tool_use_id="toolu_1"))
    assert main["subagent_stopped"] == "a1" and "subagent_seen" not in main
    assert main["state"] == "working" and main["call"] == "end" and main["event"] == "PostToolUse:TaskStop"
    inside = translate(stop({"task_id": "a1"}, agent_id="a2"))
    assert inside["subagent_stopped"] == "a1" and inside["subagent"] == "a2" and inside["subagent_seen"] is True
    assert "state" not in inside
    assert translate(stop({"shell_id": "a1"}))["subagent_stopped"] == "a1"
    assert translate(stop({"task_id": "a1", "shell_id": "b2"}))["subagent_stopped"] == "a1"
    for ti in ({}, {"task_id": ""}, {"task_id": 7}, {"shell_id": None}, None, "a1"):
        assert "subagent_stopped" not in translate(stop(ti))
    assert "subagent_stopped" not in translate({**stop({"task_id": "a1"}), "hook_event_name": "PreToolUse"})
    assert "subagent_stopped" not in translate({**stop({"task_id": "a1"}), "tool_name": "Bash"})


async def _hook(sid, **payload):
    """One hook payload, translated as the hook script does, to the host agent."""
    async with LocalClient() as h:
        await h.call("hook", session=sid, **translate(payload))


def _task_stop(task, **kw):
    return {"hook_event_name": "PostToolUse", "tool_name": "TaskStop", "tool_input": {"task_id": task}, **kw}


async def test_a_task_stop_ends_the_listed_subagent_it_names(agent, hookstub, tmp_path):
    """TD-1280, design §4.2 (TD-1277): no `SubagentStop` follows a `TaskStop` of a background subagent, so
    the stop is its end — the count and `subagent_ids` lose it and Ready to close reads *no subagents
    running*, with `subagent_at` left where it was. An id not listed (a shell's) moves nothing, a stop
    from inside a subagent ends the listed one too, and a `SubagentStop` of it afterwards moves nothing."""
    from shiftlead.ui.cards import ready_to_close

    async with LocalClient() as c:
        sid = (await c.call("create", name="t", dir=str(tmp_path), adapter=hookstub.name))["id"]
        await _hook(sid, hook_event_name="SubagentStart", agent_id="a1", agent_type="general-purpose")
        rec = await c.call("get", id=sid)
        assert rec["subagents"] == 1 and ("no subagents running", False) in ready_to_close(rec, [])
        at = rec["subagent_at"]
        await _hook(sid, **_task_stop("bq3x9"))  # a background shell's id: listed nowhere
        assert (await c.call("get", id=sid))["subagent_ids"] == ["a1"]
        await _hook(sid, **_task_stop("a1"))
        rec = await c.call("get", id=sid)
        assert rec["subagents"] == 0 and rec["subagent_ids"] == [] and rec["subagent_at"] == at
        assert ("no subagents running", True) in ready_to_close(rec, [])

        # two listed, one stopped from inside the other: one is left, and its late SubagentStop moves nothing
        await _hook(sid, hook_event_name="SubagentStart", agent_id="a2")
        await _hook(sid, hook_event_name="SubagentStart", agent_id="a3")
        await _hook(sid, **_task_stop("a2", agent_id="a3"))
        rec = await c.call("get", id=sid)
        assert rec["subagents"] == 1 and rec["subagent_ids"] == ["a3"]
        await _hook(sid, hook_event_name="SubagentStop", agent_id="a2")
        rec = await c.call("get", id=sid)
        assert rec["subagents"] == 1 and rec["subagent_ids"] == ["a3"]
        # `shell_id` names it as well
        await _hook(sid, hook_event_name="PostToolUse", tool_name="TaskStop", tool_input={"shell_id": "a3"})
        rec = await c.call("get", id=sid)
        assert rec["subagents"] == 0 and rec["subagent_ids"] == []


async def test_a_task_stop_ends_the_stopped_subagents_permission(agent, hookstub, tmp_path):
    """TD-1280: a stopped subagent's pending permission and its waiter end while another subagent stays
    counted; and an agent counted with no id stays counted, but a permission keyed by the stopped id ends."""
    ask = {"hook_event_name": "PermissionRequest", "tool_name": "Bash", "tool_input": {"command": "ls"}}
    async with LocalClient() as c:
        sid = (await c.call("create", name="p", dir=str(tmp_path), adapter=hookstub.name))["id"]
        for a in ("a1", "a2"):
            await _hook(sid, hook_event_name="SubagentStart", agent_id=a)
        perm = translate({**ask, "agent_id": "a1", "agent_type": "general-purpose"})
        task = await _feed(agent, c, sid, [perm], wait=60)
        rec = await c.call("get", id=sid)
        assert rec["state"] == "needs-you" and rec["pending"]["subagent"] == "a1"
        await _hook(sid, **_task_stop("a1"))
        assert await asyncio.wait_for(task, 5) is None and not agent._permission_waiting(sid)
        rec = await c.call("get", id=sid)
        assert rec["state"] != "needs-you" and not rec.get("pendings")
        assert rec["subagents"] == 1 and rec["subagent_ids"] == ["a2"]
        # a question in a stopped subagent's pane has no waiter: the stop ends its entry all the same
        await _hook(sid, hook_event_name="SubagentStart", agent_id="a3")
        q = {"questions": [{"question": "Which one?", "options": [{"label": "x"}, {"label": "y"}]}]}
        await _hook(sid, hook_event_name="PreToolUse", tool_name="AskUserQuestion", tool_input=q, agent_id="a3")
        rec = await c.call("get", id=sid)
        assert rec["state"] == "needs-you" and rec["pending"]["subagent"] == "a3"
        await _hook(sid, **_task_stop("a3"))
        rec = await c.call("get", id=sid)
        assert rec["state"] != "needs-you" and not rec.get("pendings") and rec["subagent_ids"] == ["a2"]

    (tmp_path / "q").mkdir()
    async with LocalClient() as c:
        sid = (await c.call("create", name="q", dir=str(tmp_path / "q"), adapter=hookstub.name))["id"]
        await c.call("hook", session=sid, subagent_delta=1, subagent_seen=True)  # an id-less start
        task = await _feed(agent, c, sid, [translate({**ask, "agent_id": "z9"})], wait=60)
        await _hook(sid, **_task_stop("z9"))
        assert await asyncio.wait_for(task, 5) is None and not agent._permission_waiting(sid)
        rec = await c.call("get", id=sid)
        assert rec["state"] != "needs-you" and rec["subagents"] == 1  # accepted: no id to match


async def test_a_task_stop_drops_the_stopped_subagents_open_calls(agent, hookstub, tmp_path):
    """TD-1288: a `TaskStop` of a subagent drops its thread's open calls, so a later permission from that id
    with the same `call_sig` is matched to no call of the stopped run; another thread's calls stay."""
    bash = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    async with LocalClient() as c:
        sid = (await c.call("create", name="o", dir=str(tmp_path), adapter=hookstub.name))["id"]
        for a in ("a1", "a2"):
            await _hook(sid, hook_event_name="SubagentStart", agent_id=a)
            await _hook(sid, hook_event_name="PreToolUse", agent_id=a, tool_use_id=f"toolu_{a}", **bash)
        sig = call_sig(bash)
        assert agent._open_calls[sid]["a1"] == [("toolu_a1", sig)]
        await _hook(sid, **_task_stop("a1"))
        assert "a1" not in agent._open_calls[sid] and agent._take_call(sid, "a1", sig) is None
        assert agent._take_call(sid, "a2", sig) == "toolu_a2"


async def test_a_queued_task_stop_still_ends_the_stopped_subagents_prompt(agent, hookstub, tmp_path):
    """TD-1288: a `TaskStop` drained from the offline queue (`queued`, older than the live state) still ends
    the stopped subagent's waiter and entry — the end runs before the `queued` gate, whatever its age."""
    ask = {"hook_event_name": "PermissionRequest", "tool_name": "Bash", "tool_input": {"command": "ls"}}
    async with LocalClient() as c:
        sid = (await c.call("create", name="u", dir=str(tmp_path), adapter=hookstub.name))["id"]
        for a in ("a1", "a2"):  # a2 stays counted, so no zero branch ends a1's prompt in the stop's place
            await _hook(sid, hook_event_name="SubagentStart", agent_id=a)
        task = await _feed(agent, c, sid, [translate({**ask, "agent_id": "a1"})], wait=60)
        assert (await c.call("get", id=sid))["pending"]["subagent"] == "a1"
        agent._apply_event(sid, {**translate(_task_stop("a1")), "at": 0.0}, queued=True)
        assert await asyncio.wait_for(task, 5) is None and not agent._permission_waiting(sid)
        rec = await c.call("get", id=sid)
        assert rec["state"] != "needs-you" and not rec.get("pendings") and rec["subagent_ids"] == ["a2"]


async def test_a_task_stop_that_ends_an_entry_is_a_sure_end(agent, hookstub, tmp_path):
    """TD-1288: the entry a `TaskStop` ends is a sure end (`_sure_end`), so the tool's late
    `permission_prompt` notice for the dialog it closed is dropped rather than read as a new prompt."""
    q = {"questions": [{"question": "Which one?", "options": [{"label": "x"}, {"label": "y"}]}]}
    async with LocalClient() as c:
        sid = (await c.call("create", name="e", dir=str(tmp_path), adapter=hookstub.name))["id"]
        await _hook(sid, hook_event_name="SubagentStart", agent_id="a1")
        await _hook(sid, hook_event_name="PreToolUse", tool_name="AskUserQuestion", tool_input=q, agent_id="a1")
        assert (await c.call("get", id=sid))["state"] == "needs-you"
        agent._sure_end.pop(sid, None)
        await _hook(sid, **_task_stop("a1"))
        assert sid in agent._sure_end and agent._notice_dropped(agent.sessions[sid])


def test_a_process_exit_forgets_the_subagent_ids(tmp_path):
    """TD-961: no subagent outlives its process, so an exit clears `subagent_ids` with the count."""
    s = Session(id="ao-x", name="x", kind="interactive", adapter="hookstub", dir=str(tmp_path))
    s.subagents, s.subagent_ids = 1, ["a1"]
    s.set_state("exited", confidence="hook")
    assert s.subagents == 0 and s.subagent_ids == []


async def test_a_main_thread_waiter_is_keyed_by_its_call(agent, hookstub, tmp_path):
    """TD-950, design §4.2 *A waiter is keyed by its call*, from the captured `subagent-permission/main/`:
    the main thread's permission is keyed by its `PreToolUse`'s `tool_use_id`, and the dialog's own
    notice leaves the waiter live and the buttons up. Its call's `PostToolUse` ends it as answered in
    the terminal; so does a new main-thread call's `PreToolUse` (a pane Deny gives the asked call no
    end), while a parallel call's end and a subagent's event end nothing."""
    events = _captured("main")
    i = next(n for n, e in enumerate(events) if e.get("kind") == "permission")
    tid = events[i - 1]["tool_use_id"]
    async with LocalClient() as c:
        sid = (await c.call("create", name="m", dir=str(tmp_path), adapter=hookstub.name))["id"]
        task = await _feed(agent, c, sid, events)
        assert events[-1].get("notice") == "permission_prompt"
        assert (sid, tid) in agent._waiters and agent._waiters[(sid, tid)][1] is None
        rec = await c.call("get", id=sid)
        assert rec["state"] == "needs-you" and rec["pending"]["kind"] == "permission"
        assert "pane_held" not in rec["pending"] and not task.done()
        await _feed(agent, c, sid, [{"subagent": "a1", "subagent_seen": True, "call": "end", "tool_use_id": "x"}])
        await _feed(agent, c, sid, [{"state": "working", "pending": None, "call": "end", "tool_use_id": "tu-par"}])
        assert not task.done()
        await _feed(agent, c, sid, [{"state": "working", "pending": None, "call": "end", "tool_use_id": tid}])
        assert await task is None
        # again, and a pane Deny: the turn's next call starts, and the asked one never ends
        task = await _feed(agent, c, sid, events[i - 1 : i + 1])
        assert (sid, tid) in agent._waiters
        nxt = {"state": "working", "pending": None, "call": "start", "tool_use_id": "tu-next", "call_sig": "0" * 16}
        await _feed(agent, c, sid, [nxt])
        assert await task is None and (await c.call("get", id=sid))["state"] == "working"


def test_a_permission_takes_the_oldest_open_call_of_its_signature(agent):
    """TD-950, design §4.2 *A waiter is keyed by its call*: each thread's open calls, matched in order by
    `call_sig`, a call leaving at its own end or once taken; the threads apart; a `SubagentStop` drops
    its thread, a reset every subagent's, the session's end all."""

    def ev(edge, tid, sig="", sub=None, **kw):
        return {"call": edge, "tool_use_id": tid, "call_sig": sig, **({"subagent": sub} if sub else {}), **kw}

    agent._track_call("s", ev("start", "A", "a"))
    agent._track_call("s", ev("start", "B", "b"))
    assert agent._take_call("s", None, "b") == "B" and agent._take_call("s", None, "b") is None
    agent._track_call("s", ev("end", "A"))
    agent._track_call("s", ev("start", "A2", "a"))
    assert agent._take_call("s", None, "a") == "A2"
    agent._track_call("s", ev("start", "C", "c", "x"))
    assert agent._take_call("s", None, "c") is None  # another thread's call
    agent._track_call("s", ev("start", "D", "d", "x"))
    agent._track_call("s", {"subagent": "x", "subagent_delta": -1})
    assert agent._take_call("s", "x", "d") is None
    for n in range(10):
        agent._track_call("s", ev("start", f"E{n}", "e"))
    assert agent._take_call("s", None, "e") == "E2"  # the last eight are kept
    for n in range(20):
        agent._track_call("s", ev("start", f"T{n}", "t", f"sub{n}"))
    assert len(agent._open_calls["s"]) == 16 and agent._take_call("s", None, "e") is None
    agent._track_call("s", {"subagents_reset": True})
    assert list(agent._open_calls["s"]) == []
    agent._track_call("s", ev("start", "F", "f"))
    agent._track_call("s", {"state": "exited"})
    assert "s" not in agent._open_calls


async def test_a_subagents_waiter_ends_with_its_subagent(agent, hookstub, tmp_path):
    """TD-950, design §4.2 *The thread scopes it*: a `SubagentStart` ends nothing; the asking subagent's
    `SubagentStop` ends its waiter, and so do the session's end and `subagents` reaching 0."""
    async with LocalClient() as c:
        sid = (await c.call("create", name="s", dir=str(tmp_path), adapter=hookstub.name))["id"]
        perm = {"kind": "permission", "text": "Bash: x", "subagent": "s1", "subagent_name": "general-purpose"}
        task = await _feed(agent, c, sid, [perm])
        await _feed(agent, c, sid, [{"subagent": "s2", "subagent_delta": 1, "subagent_seen": True}])
        await _feed(agent, c, sid, [{"subagent": "s1", "subagent_delta": 1, "subagent_seen": True}])
        assert not task.done()
        await _feed(agent, c, sid, [{"subagent": "s1", "subagent_delta": -1, "subagent_seen": True}])
        assert await task is None
        task = await _feed(agent, c, sid, [{**perm, "subagent": "s2"}])
        await _feed(agent, c, sid, [{"state": "idle", "pending": None}])  # the main thread's Stop
        assert not task.done()
        await _feed(agent, c, sid, [{"subagent_delta": -1, "subagent_seen": True}])  # the last subagent gone
        assert await task is None
        task = await _feed(agent, c, sid, [{**perm, "subagent": "s3"}])
        await _feed(agent, c, sid, [{"state": "exited", "pending": None}])
        assert await task is None


def test_hook_script_without_session_is_noop():
    env = {k: v for k, v in os.environ.items() if k != "SHIFTLEAD_SESSION"}
    cp = subprocess.run(
        [sys.executable, "-m", "shiftlead.adapters.claude_code.hook"],
        input='{"hook_event_name": "Stop"}',
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert cp.returncode == 0 and cp.stdout == ""


def test_hook_script_queues_when_agent_down(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    cp = run_hook("ao-x-y", {"hook_event_name": "Stop", "session_id": "u"})
    assert cp.returncode == 0
    q = (tmp_path / "home" / "events" / "ao-x-y.jsonl").read_text().strip()
    got = json.loads(q)
    assert isinstance(got.pop("at"), float)  # when it happened, for the drain's order (TD-169)
    assert got == {"adapter_id": "u", "state": "idle", "pending": None}


async def test_a_refused_hook_is_never_queued(agent, tmp_path):
    """TD-115: an error in the reply is the host agent answering, not an agent that is down. A
    refusal queued to `events/` was applied unjudged by the next tick — the record went `exited
    (hook)` two seconds after §4.8a refused the very event."""
    from sessionorc import identity

    agent.identity_mode = "enforce"
    async with LocalClient() as c:
        sid = (await c.call("create", name="a", dir=str(tmp_path), adapter="shell", argv=["bash", "--norc"]))["id"]
    # from the pytest process, under no pane: a hook from outside is refused
    cp = await asyncio.to_thread(run_hook, sid, {"hook_event_name": "SessionEnd", "reason": "other"})
    assert cp.returncode == 0 and cp.stdout == ""
    assert identity.MISMATCH in cp.stderr
    assert not (tmp_path / "home" / "events" / f"{sid}.jsonl").exists()
    await asyncio.sleep(0.3)  # a few ticks: nothing drains into the record
    assert agent.sessions[sid].state != "exited"


def test_pid_alive_corroborates_procstart():
    me = os.getpid()
    stat = Path(f"/proc/{me}/stat").read_text()
    my_start = int(stat[stat.rindex(")") + 2 :].split()[19])
    assert _pid_alive(me, my_start) is True
    assert _pid_alive(me, str(my_start)) is True  # the registry writes it as a string
    assert _pid_alive(me, my_start + 1) is False  # same pid, a different process
    assert _pid_alive(me, None) is True  # entry predating the field: existence only
    assert _pid_alive(2**22 + 12345, my_start) is False  # no such pid


def test_external_sessions_filters_dead_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "profiles.yml").write_text(f"profiles:\n  t: {{config_dir: {tmp_path}}}\n")
    (tmp_path / "sessions").mkdir()
    me = os.getpid()
    stat = Path(f"/proc/{me}/stat").read_text()
    start = stat[stat.rindex(")") + 2 :].split()[19]
    (tmp_path / "sessions" / "a.json").write_text(
        json.dumps(
            {"pid": me, "procStart": start, "cwd": "/w/live", "name": "live", "sessionId": "s1", "status": "busy"}
        )
    )
    (tmp_path / "sessions" / "b.json").write_text(
        json.dumps({"pid": me, "procStart": str(int(start) + 7), "cwd": "/w/stale", "sessionId": "s2"})
    )
    (tmp_path / "sessions" / "c.json").write_text(json.dumps({"pid": 2**22 + 999, "cwd": "/w/gone", "sessionId": "s3"}))
    got = ClaudeCodeAdapter().external_sessions()
    assert [(e.cwd, e.name, e.status) for e in got] == [("/w/live", "live", "busy")]


def test_external_sessions_reads_every_profiles_registry(tmp_path, monkeypatch):
    """TD-013: a second account's registry lives under its own CLAUDE_CONFIG_DIR; the anchor rule
    must see a session started there. One read per distinct dir; other tools' profiles are skipped."""
    home, a, b = tmp_path / "home", tmp_path / "claude-a", tmp_path / "claude-b"
    for d in (home, a / "sessions", b / "sessions", tmp_path / "other" / "sessions"):
        d.mkdir(parents=True)
    monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
    (home / "profiles.yml").write_text(
        f"default: a\nprofiles:\n  a: {{config_dir: {a}}}\n  a2: {{config_dir: {a}, model: sonnet}}\n"
        f"  b: {{config_dir: {b}}}\n  x: {{adapter: other-tool, config_dir: {tmp_path / 'other'}}}\n"
    )
    me = os.getpid()
    for d, name in ((a, "in-a"), (b, "in-b"), (tmp_path / "other", "not-ours")):
        (d / "sessions" / "s.json").write_text(json.dumps({"pid": me, "cwd": f"/w/{name}", "name": name}))
    got = ClaudeCodeAdapter().external_sessions()
    assert sorted(e.name for e in got) == ["in-a", "in-b"]  # once per dir, never the other tool's


def test_usage_for_by_profile_name_and_why_when_there_is_no_reading(tmp_path, monkeypatch):
    """TD-001: the core asks by profile name and gets a plain dict. TD-087: and when there is no
    reading it is told **why**, in a word it can key on — *rate-limited*, *no credentials*, *no
    profile* and *an error* were one silence, so the chip stayed empty, the journal said nothing,
    and the poll asked again a minute later against an endpoint answering 429."""
    import unittest.mock as um

    from shiftlead.adapters.claude_code import Usage, UsageRefused, Window

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))  # no profiles.yml: only `default` exists
    ad = ClaudeCodeAdapter()
    assert ad.usage_for("no-such-profile") == {"reason": "no_profile"}
    u = Usage(
        windows=[Window(label="5h", pct=42, resets="2026-09-10T04:00:00Z"), Window(label="wk", pct=7, resets=None)],
        fetched="x",
    )
    with um.patch.object(ClaudeCodeAdapter, "usage", return_value=u):
        assert ad.usage_for("") == {
            "windows": [
                {"label": "5h", "pct": 42, "resets": "2026-09-10T04:00:00Z"},
                {"label": "wk", "pct": 7, "resets": None},
            ],
            "fetched": "x",
            "reason": "ok",
        }
    with um.patch.object(ClaudeCodeAdapter, "usage", return_value=None):
        assert ad.usage_for("default") == {"reason": "error"}
    for refused, want in (
        (UsageRefused("rate_limited", 90.0), {"reason": "rate_limited", "retry_after": 90.0}),
        (UsageRefused("rate_limited"), {"reason": "rate_limited", "retry_after": None}),
        (UsageRefused("no_credentials"), {"reason": "no_credentials", "retry_after": None}),
    ):
        with um.patch.object(ClaudeCodeAdapter, "usage", side_effect=refused):
            assert ad.usage_for("default") == want


def test_a_429_is_read_as_rate_limited_with_its_retry_after(tmp_path, monkeypatch):
    """TD-087: the endpoint answers HTTP 429 `rate_limit_error` when the account's allowance is
    spent — by us, by the tool, by anything else on the same account. It is the one answer that
    means *ask less often*, so it is the one the caller must be able to tell from a network
    error; and its `Retry-After`, when it sends a number, is the endpoint's own word on when."""
    import unittest.mock as um
    import urllib.error

    from shiftlead.adapters.claude_code import UsageRefused

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    ad = ClaudeCodeAdapter()
    prof = profiles.get(None)
    with um.patch.object(ClaudeCodeAdapter, "_creds", return_value={"accessToken": "t"}):
        for err, reason, after in (
            (urllib.error.HTTPError("u", 429, "rate_limit_error", {"Retry-After": "120"}, None), "rate_limited", 120.0),
            (urllib.error.HTTPError("u", 429, "rate_limit_error", {}, None), "rate_limited", None),
            (
                urllib.error.HTTPError("u", 429, "x", {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, None),
                "rate_limited",
                None,
            ),  # noqa: E501
            (urllib.error.HTTPError("u", 500, "boom", {}, None), "error", None),
            (OSError("no route to host"), "error", None),
        ):
            with um.patch("urllib.request.urlopen", side_effect=err), pytest.raises(UsageRefused) as e:
                ad.usage(prof)
            assert (e.value.reason, e.value.retry_after) == (reason, after)
    # and no credentials never reaches the network at all
    with um.patch.object(ClaudeCodeAdapter, "_creds", return_value=None), pytest.raises(UsageRefused) as e:
        ad.usage(prof)
    assert e.value.reason == "no_credentials"


def test_composer_reads_painted_text_only():
    """TD-027: the composer is the last `❯` row; faint text (a suggested next prompt, the first-run
    placeholder) is not content; a slash command's colour is; no `❯` row means no opinion."""
    ad = ClaudeCodeAdapter()
    status = "  ⏸ manual mode on · ? for shortcuts"
    assert (
        ad.composer(["\x1b[39m❯ reply with the word tok015", "● tok015", "\x1b[39m❯\xa0real text", status])
        == "real text"
    )
    assert ad.composer(["\x1b[39m❯\xa0\x1b[2mreply with the word tok017\x1b[0m", status]) == ""
    assert ad.composer(['\x1b[39m❯\xa0\x1b[2mTry "fix typecheck errors"\x1b[0m', status]) == ""
    assert ad.composer(["\x1b[39m❯\xa0\x1b[38;5;153m/exit\x1b[39m", status]) == "/exit"
    assert ad.composer(["Do you trust the files in this folder?", "  Yes, proceed", "  No, exit"]) is None
    assert ad.composer([]) is None


def test_title_is_the_tools_own_name_for_the_session_or_nothing():
    """TD-074 step 3, design §4.3 `title()` / §4.5a **title**: the terminal title the tool set, with
    its own decoration off. What is left is a name — often the person's own, given with the tool's
    rename — unless there is nothing left, it is the tool's default, or it is a shell's
    `user@host: dir` on a pane the tool never titled. Display only: shiftlead never sets it."""
    ad = ClaudeCodeAdapter()
    assert ad.title("✳ Error Checker") == "Error Checker"  # seen on a live pane 2026-09-19
    assert ad.title("  ✻  TD-074 steps 3 and 4  ") == "TD-074 steps 3 and 4"
    assert ad.title("⣷ Error Checker") == "Error Checker"  # a spinner frame is a glyph too
    assert ad.title("Error Checker") == "Error Checker"  # undecorated, and still a name
    # one mark and only before a space: a name a person chose may open with a character of its own
    assert ad.title("* priority fix") == "* priority fix" and ad.title("•bullet") == "•bullet"
    # not a name: nothing there, the tool's own default, a shell's
    assert ad.title("") is None and ad.title("   ") is None and ad.title("✳") is None
    assert ad.title("Claude Code") is None and ad.title("✳ claude") is None
    assert ad.title("kmaster@dev: ~/agentorc") is None
    # a name that merely contains an @ is still a name
    assert ad.title("mail @ the inbox") == "mail @ the inbox"
