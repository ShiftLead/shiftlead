"""The adapter conformance suite, offline (design §4.3 *The conformance suite*, TD-784): one set of tests
every agent adapter passes, each parametrized over the registered adapters that run an agent, against
the fixtures each adapter ships under `fixtures/<adapter>/`, captured from the real tool. A declared
optional method is tested; an undeclared one is absent."""

from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path

import pytest
from _harness import (
    HARNESSES,
    RecordedProc,
    agent_adapters,
    check_background,
    check_context,
    check_conversations,
    check_declaration,
    check_hook_reading,
    check_links,
    check_prompts,
    check_spend,
    check_state,
    check_transcript,
    entry_kinds,
    fixture,
    hook_reading,
    manifest,
    pane_row,
)

from sessionorc import adapters

pytestmark = pytest.mark.unit

AGENTS = agent_adapters()


def _need(name: str, method: str, part: str) -> list[dict]:
    """The manifest's `part` for an adapter that declares `method`: a skip when it declares none, a failure
    when it declares it and ships no fixture of it (the review of #1949)."""
    ad = adapters.get(name)
    if method not in adapters.implements(ad) and not callable(getattr(ad, method, None)):
        pytest.skip(f"{name} does not declare {method}")
    got = manifest(name).get(part) or []
    if not got:
        pytest.fail(f"{name} declares {method} and ships no {part} fixtures: the live walk's --capture records them")
    return got


def _lines(name: str, rel: str) -> list[dict]:
    return [json.loads(x) for x in fixture(name, rel).read_text(encoding="utf-8").splitlines() if x.strip()]


def test_there_are_agent_adapters_and_each_ships_fixtures_and_a_harness():
    """A new agent adapter is tested from its first registration: without fixtures and a harness it fails here."""
    assert "claude-code" in AGENTS and "gemini" in AGENTS
    assert "shell" not in AGENTS and "command" not in AGENTS
    for name in AGENTS:
        assert name in HARNESSES, f"{name} has no harness in tests/conformance/_harness.py"
        assert manifest(name), f"{name} ships no tests/conformance/fixtures/{name}/manifest.json"


@pytest.mark.parametrize("name", AGENTS)
def test_the_declared_methods_are_there_and_the_rest_absent(name):
    check_declaration(adapters.get(name))


@pytest.mark.parametrize("name", AGENTS)
def test_a_system_prompt_start_context_is_a_start_context(name):
    """§4.3's contract block (TD-1669): `start_context_system` implies `start_context`, and such a `launch` takes
    `keep_context`, the conversation's file kept at a resume."""
    ad = adapters.get(name)
    if getattr(ad, "start_context_system", False):
        assert getattr(ad, "start_context", False), f"{name} says start_context_system without start_context"
        assert "keep_context" in inspect.signature(ad.launch).parameters, f"{name}'s launch takes no keep_context"


@pytest.mark.parametrize("name", AGENTS)
def test_the_constructor_takes_binary(name):
    """Every agent adapter is built with the tool it runs (§4.3's Protocol block, TD-1647): a seat's life
    builds it with `binary` set to the stub's wrapper."""
    params = inspect.signature(type(adapters.get(name))).parameters
    assert "binary" in params, f"{name}'s constructor takes no `binary`"


@pytest.mark.parametrize("name", AGENTS)
def test_each_agent_adapter_declares_its_default_home(name):
    """The home a launch uses for a profile naming no `config_dir`, which the walk and the seat smoke refuse
    (§4.3's Protocol block, TD-1648): every agent adapter declares it."""
    assert callable(getattr(adapters.get(name), "default_home", None)), f"{name} declares no default_home()"


# each agent adapter's home variable and the default it falls back to (§4.3's Protocol block): a new adapter
# fails `test_default_home_reads_the_variable_outside_a_session` until it is named here
HOME_VARIABLES = {
    "claude-code": ("CLAUDE_CONFIG_DIR", "~/.claude"),
    "gemini": ("GEMINI_CLI_HOME", "~"),
    "grok": ("GROK_HOME", "~/.grok"),
}


@pytest.mark.parametrize("name", AGENTS)
@pytest.mark.parametrize("session", [False, True])
@pytest.mark.parametrize("variable", [False, True])
def test_default_home_reads_the_variable_outside_a_session(name, session, variable, tmp_path):
    """`default_home(env)`: the tool's variable where it is set and `env` holds no `SHIFTLEAD_SESSION`, else the
    tool's own default, expanded — a session's variable is its own launch's, never the person's (TD-1648)."""
    assert name in HOME_VARIABLES, f"{name}: name its home variable in HOME_VARIABLES"
    var, default = HOME_VARIABLES[name]
    env = {"PATH": "/usr/bin"}
    if session:
        env["SHIFTLEAD_SESSION"] = "ao-x-y"
    if variable:
        env[var] = str(tmp_path / "set")
    got = adapters.get(name).default_home(env)
    want = tmp_path / "set" if variable and not session else Path(default).expanduser()
    assert got == want
    assert got == got.expanduser()


def test_shell_declares_no_permission_channel():
    assert adapters.get("shell").permission_channel is False
    assert adapters.get("command").permission_channel is False
    assert adapters.implements(adapters.get("shell")) == frozenset()


def test_claude_code_declares_its_permission_channel():
    """Design §4.3 (TD-792): Claude Code answers a pending permission through its hook channel (Allow / Deny)."""
    assert adapters.get("claude-code").permission_channel is True


@pytest.mark.parametrize("name", AGENTS)
def test_every_pane_reads_as_a_state(name):
    """A pane fixture reads as a state or as no opinion, and as what the adapter read at capture.
    A hook-fed adapter's screen rules are its `explain`; a scraped one's `classify`."""
    ad = adapters.get(name)
    for p in manifest(name).get("panes") or []:
        tail = fixture(name, p["file"]).read_text(encoding="utf-8").splitlines()
        explain = getattr(ad, "explain", None)
        got = (m.state if (m := explain(tail)) else None) if explain else ad.classify(None, tail)
        check_state(got)
        assert got == p["state"], f"{p['file']}: read {got!r}, captured as {p['state']!r}"


@pytest.mark.parametrize("name", AGENTS)
def test_the_composer_reads_what_was_painted(name):
    ad = adapters.get(name)
    panes = [p for p in _need(name, "composer", "panes") if "composer" in p]
    if not panes:
        pytest.skip(f"{name} ships no composer fixtures yet")
    for p in panes:
        tail = fixture(name, p["file"]).read_text(encoding="utf-8").splitlines()
        got = ad.composer(tail)
        assert got is None or isinstance(got, str)
        assert got == p["composer"], f"{p['file']}: composer {got!r}, captured as {p['composer']!r}"


@pytest.mark.parametrize("name", AGENTS)
def test_the_title_is_a_name_or_nothing(name):
    ad = adapters.get(name)
    for t in _need(name, "title", "titles"):
        titles = json.loads(fixture(name, t["file"]).read_text(encoding="utf-8"))
        got = [ad.title(x) for x in titles]
        for g in got:
            assert g is None or (isinstance(g, str) and g.strip() == g and g)
        assert got == t["names"], f"{t['file']}: read {got!r}, captured as {t['names']!r}"


@pytest.mark.parametrize("name", AGENTS)
def test_each_hook_payload_reads_as_a_state_and_pending(name):
    """The hook payloads the live walk captured, each through the adapter's hook to the params it hands
    the host agent, read as a state and, where the tool waits on the person, a pending kind."""
    harness = HARNESSES[name]
    if not hasattr(harness, "hook_params"):
        pytest.skip(f"{name} has no hook: its state is read from the screen")
    files = manifest(name).get("hooks") or []
    assert files, f"{name} is fed by a hook and ships no hook payload fixtures"
    for h in files:
        payloads = _lines(name, h["file"])
        assert len(payloads) == len(h["reads"]), f"{h['file']}: {len(payloads)} payloads, {len(h['reads'])} reads"
        for i, (payload, want) in enumerate(zip(payloads, h["reads"], strict=True)):
            got = hook_reading(harness.hook_params(payload, at_composer=h["at_composer"]))
            check_hook_reading(got)
            assert got == want, f"{h['file']} line {i + 1}: read {got}, captured as {want}"
    if adapters.get(name).permission_channel:
        # a declared channel answers what the tool asked: a captured permission reads as one (TD-792)
        assert any(r.get("pending") == "permission" for h in files for r in h["reads"]), "no permission captured"


@pytest.mark.parametrize("name", AGENTS)
def test_the_transcript_reads_as_neutral_entries(name, tmp_path, monkeypatch):
    harness = HARNESSES[name]
    ad = adapters.get(name)
    profile = harness.profile(tmp_path, monkeypatch)
    for i, t in enumerate(_need(name, "read_transcript", "transcripts")):
        sid = f"s{i}"
        cwd = harness.place_transcript(tmp_path, fixture(name, t["file"]), sid)
        tr = ad.read_transcript(sid, cwd, profile)
        check_transcript(tr, harness.tool_fields)
        assert tr.turns == t["turns"]
        assert entry_kinds(tr) == set(t["kinds"]), f"{t['file']}: kinds {sorted(entry_kinds(tr))}"
        raw = ad.read_transcript(sid, cwd, profile, raw=True, turns=3)
        assert isinstance(raw.raw, str) and len(raw.raw.splitlines()) == 3
        assert ad.read_transcript("no-such-session", cwd, profile) is None


@pytest.mark.parametrize("name", AGENTS)
def test_context_is_the_last_turns_prompt_within_its_window(name, tmp_path, monkeypatch):
    harness = HARNESSES[name]
    ad = adapters.get(name)
    profile = harness.profile(tmp_path, monkeypatch)
    for i, t in enumerate(_need(name, "context", "transcripts")):
        sid = f"s{i}"
        cwd = harness.place_transcript(tmp_path, fixture(name, t["file"]), sid)
        got = ad.context(sid, cwd, profile)
        check_context(got)
        assert {"tokens": got["tokens"], "window": got["window"]} == t["context"]
        assert ad.context("no-such-session", cwd, profile) is None


@pytest.mark.parametrize("name", AGENTS)
def test_links_are_the_urls_printed_and_a_cursor(name, tmp_path, monkeypatch):
    harness = HARNESSES[name]
    ad = adapters.get(name)
    profile = harness.profile(tmp_path, monkeypatch)
    for i, t in enumerate(_need(name, "links", "transcripts")):
        sid = f"s{i}"
        cwd = harness.place_transcript(tmp_path, fixture(name, t["file"]), sid)
        got = ad.links(sid, cwd, profile, cursor=0)
        check_links(got)
        assert [link.url for link in got[0]] == t["links"]
        again = ad.links(sid, cwd, profile, cursor=got[1])
        check_links(again)
        assert again[0] == [] and again[1] == got[1]  # nothing new past the cursor
        assert ad.links("no-such-session", cwd, profile) is None


@pytest.mark.parametrize("name", AGENTS)
def test_prompts_are_what_was_typed_each_opening_a_row_of_the_pane(name, tmp_path, monkeypatch):
    """The `prompts` read (design §4.3 `prompts`, §4.2 *The record's `prompts`*, TD-976) on a captured
    conversation: the lines typed, each reply's first line, and each `drawn` opening a row of the pane the
    same conversation drew — equal to it where `whole`."""
    harness = HARNESSES[name]
    ad = adapters.get(name)
    profile = harness.profile(tmp_path, monkeypatch)
    for i, t in enumerate(_need(name, "prompts", "prompts")):
        sid = f"s{i}"
        cwd = harness.place_transcript(tmp_path, fixture(name, t["file"]), sid)
        got = ad.prompts(sid, cwd, profile, cursor=0)
        check_prompts(got)
        found, leading, cursor = got
        assert [{"text": p.text, "reply": p.reply} for p in found] == t["prompts"]
        assert leading is None
        rows = [pane_row(r) for r in fixture(name, t["pane"]).read_text(encoding="utf-8").splitlines()]
        for p in found:
            if p.drawn is None:
                continue
            drawn = pane_row(p.drawn)
            if p.whole:
                assert drawn in rows, f"no row of {t['pane']} is {drawn!r}"
            else:
                assert any(r.startswith(drawn) for r in rows), f"no row of {t['pane']} opens {drawn!r}"
        again = ad.prompts(sid, cwd, profile, cursor=cursor)
        check_prompts(again)
        assert again == ([], None, cursor)  # nothing new past the cursor
        assert ad.prompts("no-such-session", cwd, profile) is None


@pytest.mark.parametrize("name", AGENTS)
def test_spend_reports_neutral_turns_with_four_token_kinds(name, tmp_path, monkeypatch):
    harness = HARNESSES[name]
    ad = adapters.get(name)
    profile = harness.profile(tmp_path, monkeypatch)
    transcripts = _need(name, "spend", "transcripts")
    for i, t in enumerate(transcripts):
        harness.place_transcript(tmp_path, fixture(name, t["file"]), f"s{i}")
    got = ad.spend(profile, {})
    check_spend(got, harness.tool_fields)
    assert got["reason"] == "ok"
    assert len(got["turns"]) == sum(t["spend_turns"] for t in transcripts)
    again = ad.spend(profile, got["cursors"])
    assert again["turns"] == [] and again["cursors"] == got["cursors"]


@pytest.mark.parametrize("name", AGENTS)
def test_conversations_list_the_directorys_files_oldest_first(name, tmp_path, monkeypatch):
    """The `conversations` read (design §4.3 `conversations`, TD-1491) on captured files: each conversation of
    the cwd with its first and last instants and its bytes, oldest first; a file with no timestamped entry,
    another directory's and a subagent's left out; None for an unknown profile, [] for a cwd with none."""
    harness = HARNESSES[name]
    ad = adapters.get(name)
    profile = harness.profile(tmp_path, monkeypatch)
    for entry in _need(name, "conversations", "conversations"):
        cwd = harness.place_conversations(tmp_path, entry, name)
        got = ad.conversations(cwd, profile)
        check_conversations(got)
        assert [c.to_dict() for c in got] == entry["conversations"]
        assert ad.conversations(tmp_path / "nowhere", profile) == []
        assert ad.conversations(cwd, "no-such-profile") is None


@pytest.mark.parametrize("name", AGENTS)
def test_a_failed_call_is_marked_only_where_the_adapter_marks_errors(name, tmp_path, monkeypatch):
    """`marks_errors` (design §4.3 `read_transcript`, TD-1491): an adapter that marks them ships a captured
    failed call and marks exactly it, `to_dict` carrying `error` only when True; one that does not leaves
    every tool entry's `error` False."""
    harness = HARNESSES[name]
    ad = adapters.get(name)
    profile = harness.profile(tmp_path, monkeypatch)
    if not adapters.marks_errors(ad):
        for i, t in enumerate(manifest(name).get("transcripts") or []):
            cwd = harness.place_transcript(tmp_path, fixture(name, t["file"]), f"e{i}")
            tr = ad.read_transcript(f"e{i}", cwd, profile, turns=1000)
            assert not any(e.error for e in tr.entries if e.kind == "tool")
        return
    files = manifest(name).get("failed_calls") or []
    if not files:
        pytest.fail(f"{name} marks errors and ships no failed_calls fixture")
    for i, t in enumerate(files):
        cwd = harness.place_transcript(tmp_path, fixture(name, t["file"]), f"f{i}")
        tr = ad.read_transcript(f"f{i}", cwd, profile, turns=1000)
        check_transcript(tr, harness.tool_fields)
        tools = [e for e in tr.entries if e.kind == "tool"]
        assert [e.error for e in tools] == t["errors"]
        assert [("error" in e.to_dict()) for e in tools] == t["errors"]


@pytest.mark.parametrize("name", AGENTS)
def test_background_reads_the_tools_shell_tasks(name):
    ad = adapters.get(name)
    for p in _need(name, "background", "procs"):
        snap = json.loads(fixture(name, p["file"]).read_text(encoding="utf-8"))
        proc = RecordedProc(snap["procs"])
        got = ad.background(snap["pane_pid"], proc)
        check_background(got)
        assert [t["cmd"] for t in got] == p["background"]
        assert ad.background(1, RecordedProc({})) is None  # no tool process under it: no opinion


@pytest.mark.parametrize("name", AGENTS)
def test_usage_report_reads_the_windows_a_session_was_told(name):
    ad = adapters.get(name)
    for p in _need(name, "usage_report", "status_lines"):
        counts = []
        for payload in _lines(name, p["file"]):
            got = ad.usage_report(payload)
            assert got is None or {"windows", "work", "sid"} <= set(got)
            for w in (got or {}).get("windows") or ():
                assert set(w) == {"label", "pct", "resets"}, f"a window is {w!r}"
            counts.append(len((got or {}).get("windows") or ()))
        assert counts == p["windows"], f"{p['file']}: windows {counts}, captured as {p['windows']}"


@pytest.mark.parametrize("name", AGENTS)
def test_mail_says_how_a_session_is_handed_its_mail(name):
    ad = adapters.get(name)
    if "mail" not in adapters.implements(ad):
        pytest.skip(f"{name} does not declare mail: its sessions are handed mail by a pane write")
    ad.mail()  # None, or a delivery: never an error


# -- the Tools page's reads (design §4.2b *What the adapter reads*, TD-1971) -------------------------------


def _declares(name: str, method: str):
    ad = adapters.get(name)
    if method not in adapters.implements(ad):
        pytest.skip(f"{name} does not declare {method}")
    return ad


@pytest.mark.parametrize("name", AGENTS)
def test_find_is_the_binary_by_absolute_path_or_none(name, tmp_path):
    """`find()` asks for the binary a launch would run without launching it: by absolute path, or None."""
    ad = _declares(name, "find")
    stub = tmp_path / "bin" / "tool"
    stub.parent.mkdir()
    stub.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")  # never run: a run would be a launch
    stub.chmod(0o755)
    assert type(ad)(binary=str(stub)).find() == str(stub)
    assert type(ad)(binary=str(tmp_path / "missing")).find() is None


@pytest.mark.parametrize("name", AGENTS)
def test_home_env_is_empty_for_the_default_home_and_names_any_other(name, tmp_path):
    """`home_env(home)` is what a launch on `home` sets: nothing for the tool's default home, as a launch on a
    profile with no `config_dir` sets nothing; another home named in it, every key and value a string."""
    ad = _declares(name, "home_env")
    assert ad.home_env(ad.default_home(os.environ)) == {}
    login = tmp_path / "login"
    env = ad.home_env(login)
    assert env and all(isinstance(k, str) and isinstance(v, str) for k, v in env.items())
    assert str(login) in env.values()


@pytest.mark.parametrize("name", AGENTS)
def test_credentials_ok_reads_a_home_given_as_a_path(name, tmp_path, monkeypatch):
    """`credentials_ok` takes a home as a path beside a profile (§4.2b): None before a sign-in, True after."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    ad = adapters.get(name)
    login = tmp_path / "login"
    login.mkdir()
    assert ad.credentials_ok(login) is None
    HARNESSES[name].sign_in(login)
    assert ad.credentials_ok(login) is True


@pytest.mark.parametrize("name", AGENTS)
def test_is_home_reads_what_the_tool_writes_there(name, tmp_path):
    """`is_home(path)`: a folder is the tool's home by the files the tool writes there, never by settings a repo
    holds too, nor ShiftLead's own files."""
    ad = _declares(name, "is_home")
    harness = HARNESSES[name]
    folder = tmp_path / "folder"
    folder.mkdir()
    assert ad.is_home(folder) is False
    harness.not_a_home(folder)
    assert ad.is_home(folder) is False
    harness.mark_home(folder)
    assert ad.is_home(folder) is True


@pytest.mark.parametrize("name", AGENTS)
def test_new_home_suggests_a_folder_and_make_home_makes_one_a_sign_in_fills(name, tmp_path, monkeypatch):
    """`new_home(name)` suggests a new login's folder beside the tool's default, its name in it, and makes nothing;
    `make_home(path)` makes any folder one the tool's sign-in can write into, 0700, and a home only once signed in."""
    ad = _declares(name, "new_home")
    monkeypatch.setenv("HOME", str(tmp_path))
    got = ad.new_home("work-2")
    assert isinstance(got, Path) and got.is_absolute() and "work-2" in got.name and not got.exists()
    assert not adapters.same_home(got, ad.default_home({}))
    ad = _declares(name, "make_home")
    folder = tmp_path / "deep" / "login"
    ad.make_home(folder)
    assert folder.is_dir() and folder.stat().st_mode & 0o777 == 0o700 and ad.is_home(folder) is False
    ad.make_home(folder)  # again: nothing changes
    HARNESSES[name].mark_home(folder)
    assert ad.is_home(folder) is True


@pytest.mark.parametrize("name", AGENTS)
def test_env_signin_reads_the_environment_it_is_given(name):
    """`env_signin(env)` is True for the environment whose one key signs in every login, False for an empty one."""
    ad = _declares(name, "env_signin")
    assert ad.env_signin({}) is False
    assert ad.env_signin(HARNESSES[name].signin_env) is True


@pytest.mark.parametrize("name", AGENTS)
def test_install_and_signin_commands_are_the_persons_to_run(name):
    """`install_command()` is one line of text; `signin_command()` an argv whose first word is the binary."""
    ad = _declares(name, "install_command")
    line = ad.install_command()
    assert isinstance(line, str) and line.strip() and "\n" not in line
    ad = _declares(name, "signin_command")
    argv = ad.signin_command()
    assert argv and all(isinstance(a, str) for a in argv) and argv[0] == ad.binary


def _signed_in(name: str, root: Path, folder: str, key: str, display: str = "Ada") -> Path:
    home = root / folder
    home.mkdir()
    HARNESSES[name].sign_in_as(home, key, display)
    return home


@pytest.mark.parametrize("name", AGENTS)
def test_identity_is_none_before_a_sign_in_and_on_a_record_it_cannot_read(name, tmp_path):
    """`identity(home, salt)` is None with no account recorded, and None, never an exception, on a broken record."""
    ad = _declares(name, "identity")
    home = tmp_path / "login"
    home.mkdir()
    assert ad.identity(home, b"salt") is None
    harness = HARNESSES[name]
    for text in harness.corrupt_identity(home):
        harness.write_identity(home, text)
        assert ad.identity(home, b"salt") is None, text


@pytest.mark.parametrize("name", AGENTS)
def test_identity_matches_compare_within_one_salt_only(name, tmp_path):
    """One key under two salts gives two matches; two homes with one key give one; two keys give two (§4.2b)."""
    ad = _declares(name, "identity")
    one = _signed_in(name, tmp_path, "one", "acct-1@example.com")
    two = _signed_in(name, tmp_path, "two", "acct-1@example.com")
    other = _signed_in(name, tmp_path, "other", "acct-2@example.com")
    a, b = ad.identity(one, b"salt-a"), ad.identity(one, b"salt-b")
    assert a["match"] != b["match"]
    assert ad.identity(two, b"salt-a")["match"] == a["match"]
    assert ad.identity(other, b"salt-a")["match"] != a["match"]
    assert set(a) == {"match", "display", "plan", "billing"}
    assert a["billing"] in ("subscription", "metered", None)
    assert a["plan"] is None or isinstance(a["plan"], str)


@pytest.mark.parametrize("name", AGENTS)
def test_identity_never_lets_the_account_key_out(name, tmp_path, caplog, capsys):
    """The key never leaves the adapter: not in the reply, a log line or printed output (§4.2b); `display` is a
    name, never an email or part of one."""
    ad = _declares(name, "identity")
    key = "f00dfeed-secret-key@example.com"
    caplog.set_level("DEBUG")
    home = _signed_in(name, tmp_path, "login", key, display="Ada")
    reply = ad.identity(home, b"salt")
    assert reply is not None and reply["display"] in ("Ada", None)
    seen = repr(reply) + caplog.text + "".join(capsys.readouterr())
    assert "f00dfeed" not in seen and key not in seen
    emailed = _signed_in(name, tmp_path, "emailed", key, display="ada@example.com")
    assert ad.identity(emailed, b"salt")["display"] is None


@pytest.mark.parametrize("name", AGENTS)
def test_models_offers_the_plans_families_or_every_family_unconfirmed(name, tmp_path):
    """`models(home, plan)` (§4.2b): a plan the adapter's table knows offers its families, confirmed; one it does not
    know offers the whole list, `unconfirmed`; `default` a family the adapter knows, or None."""
    ad = _declares(name, "models")
    mod = sys.modules[type(ad).__module__]
    home = tmp_path / "login"
    home.mkdir()
    unknown = ad.models(home, "a plan nobody has")
    assert set(unknown) == {"families", "default", "unconfirmed"}
    assert unknown["unconfirmed"] is True and unknown["families"] == list(mod.FAMILIES)
    assert ad.models(home, None)["unconfirmed"] is True
    for plan, families in mod.PLAN_FAMILIES.items():
        got = ad.models(home, plan)
        assert got["unconfirmed"] is False and got["families"] == list(families)
        assert set(families) <= set(mod.FAMILIES)
    assert unknown["default"] is None or unknown["default"] in mod.FAMILIES


@pytest.mark.parametrize("name", AGENTS)
def test_each_family_is_read_from_the_models_names_it_covers(name):
    """The adapter's table maps a model's name to its family (§4.2b `models`, the switch-over's pin): every family is
    some name's, and a name the table does not cover is none. The adapter's own `model_family`, which the switch-over
    reads, answers as its module's table does (TD-2177)."""
    ad = _declares(name, "model_family")
    assert "models" in adapters.implements(ad), "model_family reads the table that models offers"
    mod = sys.modules[type(ad).__module__]
    assert mod.model_family("no-such-model") is None and mod.model_family(None) is None
    assert ad.model_family("no-such-model") is None
    for family, model in NAMED_MODELS[name]:
        assert mod.model_family(model) == family, model
        assert ad.model_family(model) == family, model
    assert {f for f, _ in NAMED_MODELS[name]} == set(mod.FAMILIES)


# names each tool has run on kmaster (TD-1971), one or more per family
NAMED_MODELS = {
    "claude-code": [
        ("fable", "claude-fable-5-2"),
        ("opus", "claude-opus-5-5"),
        ("opus", "opus[1m]"),
        ("sonnet", "sonnet"),
        ("haiku", "claude-haiku-5-5"),
    ],
    "gemini": [
        ("flash-lite", "gemini-3.5-flash-lite"),
        ("flash", "gemini-3-flash-preview"),
        ("flash", "gemini-3.8-flash"),
        ("pro", "gemini-3.5-pro"),
    ],
    "grok": [("grok", "grok-4.7"), ("build-fast", "grok-4.7-build-fast")],
}


# the settings file naming a model in a home, where the adapter reads its default from one (§4.2b `models`)
DEFAULT_SETTINGS = {
    "claude-code": ("settings.json", {"model": "claude-sonnet-5-5"}, "sonnet"),
    "gemini": (".gemini/settings.json", {"model": {"name": "gemini-3.5-flash-lite"}}, "flash-lite"),
}


@pytest.mark.parametrize("name", AGENTS)
def test_models_default_is_the_family_the_homes_settings_name(name, tmp_path):
    """`default` is the family of the model the home's settings name, and None where they name none."""
    ad = _declares(name, "models")
    if name not in DEFAULT_SETTINGS:
        pytest.skip(f"{name} reads no default from a file")
    rel, doc, family = DEFAULT_SETTINGS[name]
    home = tmp_path / "login"
    (home / rel).parent.mkdir(parents=True)
    assert ad.models(home, None)["default"] is None
    (home / rel).write_text(json.dumps(doc), encoding="utf-8")
    assert ad.models(home, None)["default"] == family
