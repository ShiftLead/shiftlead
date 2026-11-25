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
