"""The adapter conformance suite, offline (design §4.3 *The conformance suite*, TD-784): one set of tests
every agent adapter passes, each parametrized over the registered adapters that run an agent, against
the fixtures each adapter ships under `fixtures/<adapter>/`, captured from the real tool. A declared
optional method is tested; an undeclared one is absent."""

from __future__ import annotations

import json

import pytest
from _harness import (
    HARNESSES,
    RecordedProc,
    agent_adapters,
    check_background,
    check_context,
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
