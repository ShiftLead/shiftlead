"""TD-2068, design §4.9e *The launch on a login*: a `create` naming a login resolves it in its own host's `logins.yml`,
launches on the name the login is read under as a profile with the seat model handed to the adapter's launch, and
writes `login`, `account` (node-owned), `seat_model` and `login_list` (home-owned) on the record; a launch with no
login is unchanged, and what does not fit a login is refused before anything is made."""

from __future__ import annotations

from pathlib import Path

import pytest

from sessionorc import logins, paths
from sessionorc.adapters import LaunchSpec
from sessionorc.agent_common import LAUNCH_KEYS, RpcError, _on_login
from sessionorc.client import AgentError, LocalClient
from sessionorc.models import HOME_OWNED, NODE_OWNED, Session, apply_node
from shiftlead import profiles
from shiftlead.adapters.claude_code import ClaudeCodeAdapter

LOGINS = """logins:
  hookstub:grind: {folder: /c/grind, account: acct-1, pin: sonnet}
  hookstub:twin: {folder: /c/t1}
  claude-code:twin: {folder: /c/t2}
accounts: {}
forgotten: {}
"""


@pytest.mark.unit
def test_the_fields_have_one_owner_each_and_a_launch_record_keeps_the_homes():
    assert {"login", "account"} <= NODE_OWNED and not {"login", "account"} & HOME_OWNED
    assert {"seat_model", "login_list"} <= HOME_OWNED and not {"seat_model", "login_list"} & NODE_OWNED
    assert {"login", "seat_model", "login_list"} <= set(LAUNCH_KEYS), "a replay launches on the same login"
    home = Session(id="a", name="a", kind="interactive", adapter="claude-code", dir="/")
    assert (home.login, home.account, home.seat_model, home.login_list) == (None, None, None, None)
    got = apply_node(home, {**home.to_dict(), "login": "claude-code:grind", "account": "acct-1", "seat_model": "x"})
    assert (got.login, got.account, got.seat_model) == ("claude-code:grind", "acct-1", None), "a node's own two"


@pytest.mark.unit
def test_profile_name_is_the_bare_name_unless_two_tools_share_it(tmp_path):
    (tmp_path / "logins.yml").write_text(LOGINS)
    data = logins.load(tmp_path)
    assert logins.profile_name(data, "hookstub:grind") == "grind"
    assert logins.profile_name(data, "hookstub:twin") == "hookstub:twin"
    got, _ = profiles.load(tmp_path / "profiles.yml")
    assert "grind" in got and "hookstub:twin" in got and "twin" not in got, "the reader keys a login the same way"


@pytest.mark.unit
def test_a_login_resolves_to_its_key_account_and_profile_name(tmp_path):
    (tmp_path / "logins.yml").write_text(LOGINS)
    got = _on_login("grind", "hookstub", "", "opus", ["hookstub:grind", "hookstub:twin"], tmp_path)
    assert got == {
        "login": "hookstub:grind",
        "account": "acct-1",
        "profile": "grind",
        "login_list": ["hookstub:grind", "hookstub:twin"],
    }
    twin = _on_login("hookstub:twin", "hookstub", "hookstub:twin", None, None, tmp_path)
    assert (twin["account"], twin["profile"], twin["login_list"]) == ("hookstub:twin", "hookstub:twin", None)
    assert _on_login(None, "hookstub", "grind", None, None, tmp_path) is None, "no login: a profile's launch"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("login", "adapter", "profile", "model", "order", "words"),
    [
        (None, "hookstub", "", "opus", None, "ride a launch on a login"),
        (None, "hookstub", "", None, ["hookstub:grind"], "ride a launch on a login"),
        ("nobody", "hookstub", "", None, None, "no login nobody on this host"),
        ("twin", "hookstub", "", None, None, "names more than one login"),
        ("grind", "claude-code", "", None, None, "runs hookstub, not claude-code"),
        ("grind", "hookstub", "other", None, None, "names no profile of its own"),
        ("grind", "hookstub", "", "  ", None, "a model family's name"),
        ("grind", "hookstub", "", None, "hookstub:grind", "the logins' keys in order"),
    ],
    ids=["model-alone", "list-alone", "unknown", "ambiguous", "other-tool", "other-profile", "blank-model", "list-str"],
)
def test_what_does_not_fit_a_login_is_refused(tmp_path, login, adapter, profile, model, order, words):
    (tmp_path / "logins.yml").write_text(LOGINS)
    with pytest.raises(RpcError, match=words):
        _on_login(login, adapter, profile, model, order, tmp_path)


@pytest.mark.unit
def test_a_host_with_no_logins_file_refuses_a_login(tmp_path):
    with pytest.raises(RpcError, match="holds no logins.yml"):
        _on_login("grind", "hookstub", "", None, None, tmp_path)


@pytest.mark.unit
def test_claude_codes_launch_runs_the_model_given_over_the_profiles_pin(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "logins.yml").write_text(
        "logins:\n  claude-code:grind: {folder: " + str(tmp_path / "cfg") + ", pin: sonnet}\n"
    )
    (tmp_path / "w").mkdir()
    ad = ClaudeCodeAdapter(binary="claude")
    pinned = ad.launch(profile="grind", resume=None, prompt=None, unattended=True, cwd=tmp_path / "w")
    given = ad.launch(profile="grind", resume=None, prompt=None, unattended=True, cwd=tmp_path / "w", model="opus")
    assert pinned.argv[pinned.argv.index("--model") + 1] == "sonnet"
    assert given.argv[given.argv.index("--model") + 1] == "opus"
    assert given.argv.count("--model") == 1


def _pinned_login(tmp_path: Path, monkeypatch, tool: str) -> None:
    """A home whose `logins.yml` holds `<tool>:grind`, pinned to `pinned`, and the launch's working directory."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "logins.yml").write_text(
        "logins:\n  " + tool + ":grind: {folder: " + str(tmp_path / "cfg") + ", pin: pinned}\n"
    )
    (tmp_path / "w").mkdir()


def _the_model(spec: LaunchSpec) -> str:
    assert spec.argv.count("--model") == 1, spec.argv
    return spec.argv[spec.argv.index("--model") + 1]


@pytest.mark.unit
def test_geminis_launch_runs_the_model_given_over_the_logins_pin(tmp_path, monkeypatch):
    from test_gemini_adapter import rooted

    from shiftlead.adapters import gemini

    _pinned_login(tmp_path, monkeypatch, "gemini")
    machine = tmp_path / "etc" / "gemini-settings.json"  # the machine layer, installed: never this machine's own
    monkeypatch.setattr(gemini, "MACHINE_LAYER", machine)
    monkeypatch.setattr(gemini, "_lstat", rooted())
    machine.parent.mkdir()
    machine.write_text(gemini.write_layer().read_text())
    ad = gemini.GeminiAdapter(binary="/opt/gemini")
    kw = {"profile": "grind", "resume": None, "prompt": None, "unattended": True, "cwd": tmp_path / "w"}
    assert _the_model(ad.launch(**kw)) == "pinned"
    assert _the_model(ad.launch(**kw, model="given")) == "given", "a launch on a login runs the seat model (§4.9e)"


@pytest.mark.unit
def test_groks_launch_runs_the_model_given_over_the_logins_pin(tmp_path, monkeypatch):
    from shiftlead.adapters import grok

    _pinned_login(tmp_path, monkeypatch, "grok")
    binary = tmp_path / "bin" / "grok"
    binary.parent.mkdir()
    binary.write_text("#!/bin/sh\n")
    (tmp_path / "person").mkdir()  # the launch home's source: never the developer's (TD-1836)
    monkeypatch.setattr(grok, "PERSON_HOME", tmp_path / "person")
    monkeypatch.setattr(grok, "MANAGED_SETTINGS", tmp_path / "etc" / "managed-settings.json")
    ad = grok.GrokAdapter(binary=str(binary), hook_cmd="/venv/bin/shiftlead-hook")
    kw = {"profile": "grind", "resume": None, "prompt": None, "unattended": True, "cwd": tmp_path / "w"}
    assert _the_model(ad.launch(**kw)) == "pinned"
    assert _the_model(ad.launch(**kw, model="given")) == "given", "a launch on a login runs the seat model (§4.9e)"


@pytest.fixture
def launched(hookstub, monkeypatch):
    """The stub adapter's launch, recording what each was handed."""
    seen: list[dict] = []

    def launch(*, profile, resume, prompt, unattended, cwd, name="", **kw):
        seen.append({"profile": profile, **kw})
        return LaunchSpec(argv=["bash", "--norc"])

    monkeypatch.setattr(hookstub, "launch", launch)
    return seen


def _params(tmp_path: Path, name: str, **kw) -> dict:
    (tmp_path / name).mkdir(exist_ok=True)
    return {"name": name, "dir": str(tmp_path / name), "adapter": "hookstub", "unattended": True, **kw}


async def test_a_create_on_a_login_launches_on_it_and_writes_the_record(agent, tmp_path, launched):
    (paths.home() / "logins.yml").write_text(LOGINS)
    order = ["hookstub:grind", "hookstub:twin"]
    async with LocalClient() as person:
        sid = (
            await person.call(
                "create", **_params(tmp_path, "build-td-1", login="grind", seat_model="opus", login_list=order)
            )
        )["id"]
        plain = (await person.call("create", **_params(tmp_path, "plain")))["id"]
    s = agent.sessions[sid]
    assert (s.login, s.account, s.seat_model, s.login_list, s.profile) == (
        "hookstub:grind",
        "acct-1",
        "opus",
        order,
        "grind",
    )
    assert launched[0] == {"profile": "grind", "model": "opus"}, "the login's profile name and the seat model"
    p = agent.sessions[plain]
    assert (p.login, p.account, p.seat_model, p.login_list) == (None, None, None, None)
    assert launched[1] == {"profile": ""}, "a launch with no login is handed no model"


async def test_a_create_on_a_login_this_host_lacks_makes_nothing(agent, tmp_path, launched):
    (paths.home() / "logins.yml").write_text(LOGINS)
    async with LocalClient() as person:
        with pytest.raises(AgentError, match="no login nobody on this host"):
            await person.call("create", **_params(tmp_path, "w", login="nobody", seat_model="opus"))
    assert not launched and not agent.sessions


async def test_a_held_seat_on_a_login_holds_its_login_fields(agent, tmp_path, launched):
    """A held record is written by `_schedule`, not the launch: it carries the login's fields too (review of #4688)."""
    (paths.home() / "logins.yml").write_text(LOGINS)
    async with LocalClient() as person:
        sid = (
            await person.call(
                "create",
                **_params(
                    tmp_path,
                    "techlead",
                    supervised=True,
                    held=True,
                    seat={"trigger": "asks"},
                    login="grind",
                    seat_model="opus",
                    login_list=["hookstub:grind"],
                ),
            )
        )["id"]
    s = agent.sessions[sid]
    assert s.state == "closed" and not launched
    assert (s.login, s.account, s.seat_model, s.login_list, s.profile) == (
        "hookstub:grind",
        "acct-1",
        "opus",
        ["hookstub:grind"],
        "grind",
    )


async def test_the_persons_create_on_a_login_is_the_last_used_for_its_tool(agent, tmp_path, launched):
    """§4.9e *The launch on a login*: the host agent remembers, per tool, the login of the last create the person made
    on one (`last_login`, beside `recent_dirs`); a team's or a seat's launch writes nothing, and a stored login this
    host's `logins.yml` no longer holds reads as nothing stored."""
    (paths.home() / "logins.yml").write_text(LOGINS)
    async with LocalClient() as person:
        assert await person.call("last_login") == {}, "nothing stored yet"
        await person.call("create", **_params(tmp_path, "mine", login="grind"))
        await person.call("create", **_params(tmp_path, "team", login="hookstub:twin", supervised=True, team="t"))
        await person.call(
            "create",
            **_params(tmp_path, "seat", login="hookstub:twin", supervised=True, held=True, seat={"trigger": "asks"}),
        )
        assert await person.call("last_login") == {"hookstub": "hookstub:grind"}, "a team's or a seat's writes none"
        await person.call("create", **_params(tmp_path, "cc", adapter="claude-code", login="claude-code:twin"))
        await person.call("create", **_params(tmp_path, "again", login="hookstub:twin"))
        assert await person.call("last_login") == {"hookstub": "hookstub:twin", "claude-code": "claude-code:twin"}
        (paths.home() / "logins.yml").write_text(LOGINS.replace("  hookstub:twin: {folder: /c/t1}\n", ""))
        assert await person.call("last_login") == {"claude-code": "claude-code:twin"}, "a login gone is none stored"


async def test_an_unwritable_or_unreadable_last_login_never_fails_a_create(agent, tmp_path, launched, monkeypatch):
    """Review of #4734: `last_login` is a convenience file. A create whose write of it fails stands (the write is
    after the record is saved, as `recent_dirs`' is), and a file that cannot be read, or a line whose key is another
    tool's, reads as nothing stored."""
    (paths.home() / "logins.yml").write_text(LOGINS)

    def refuse(self, login):
        raise OSError("read-only")

    monkeypatch.setattr(type(agent), "_remember_login", refuse)
    async with LocalClient() as person:
        sid = (await person.call("create", **_params(tmp_path, "mine", login="grind")))["id"]
        assert agent.sessions[sid].login == "hookstub:grind", "the create stood"
        paths.last_login_file().write_bytes(b"\xff\xfe not text")
        assert await person.call("last_login") == {}, "an unreadable file is nothing stored"
        paths.last_login_file().write_text("claude-code hookstub:grind\nnospace\nhookstub hookstub:twin\n")
        assert await person.call("last_login") == {"hookstub": "hookstub:twin"}, "another tool's key is skipped"


async def test_a_create_replaces_an_unreadable_last_login(agent, tmp_path, launched):
    """Re-review of #4734: the real write over a file that is not text replaces it rather than failing the create."""
    (paths.home() / "logins.yml").write_text(LOGINS)
    paths.last_login_file().write_bytes(b"\xff\xfe not text")
    async with LocalClient() as person:
        await person.call("create", **_params(tmp_path, "mine", login="grind"))
        assert await person.call("last_login") == {"hookstub": "hookstub:grind"}
