"""The `ao login` and `ao account` verbs (design §4.2b *Controls and verbs*, TD-1974): each edit on the file, the
rules that refuse one, the RPCs as a person's own acts refused before the switch-over, and the CLI's calls."""

from __future__ import annotations

import pytest
import yaml

from sessionorc import logins


def _data() -> dict:
    d = logins.empty()
    d["logins"]["claude-code:paul"] = {"folder": "/h/.claude", "account": "claude-code:paul-k"}
    d["logins"]["claude-code:grind"] = {"folder": "/h/.claude-grind", "account": "claude-code:paul-k"}
    d["logins"]["gemini:paul"] = {"folder": "/h"}
    d["logins"]["claude-code:api"] = {"folder": "/h/.claude-api"}
    d["accounts"]["claude-code:paul-k"] = {"label": "Paul"}
    return d


def test_a_label_and_a_note_are_one_line_and_none_clears_them():
    d = _data()
    assert logins.label_login(d, "grind", "work laptop") == "claude-code:grind labelled 'work laptop'"
    assert d["logins"]["claude-code:grind"]["label"] == "work laptop"
    assert "label cleared" in logins.label_login(d, "claude-code:grind", "")
    assert "label" not in d["logins"]["claude-code:grind"]
    with pytest.raises(logins.LoginError, match="more than one login"):
        logins.label_login(d, "paul", "x")  # two tools have it: say which
    with pytest.raises(logins.LoginError, match="one line"):
        logins.note_login(d, "grind", "a\nb")
    with pytest.raises(logins.LoginError, match="at most"):
        logins.label_login(d, "grind", "x" * (logins.LABEL_MAX + 1))
    assert "note set" in logins.note_login(d, "gemini:paul", "the free tier")
    assert d["logins"]["gemini:paul"]["note"] == "the free tier"
    assert "note cleared" in logins.note_login(d, "gemini:paul", None)
    with pytest.raises(logins.LoginError, match="no login nobody"):
        logins.note_login(d, "nobody", "x")


def test_a_write_over_a_newer_version_is_refused():
    d = _data()
    old = logins.version(d["logins"]["claude-code:grind"])
    logins.label_login(d, "grind", "one", old)
    with pytest.raises(logins.LoginError, match="changed since this page read it — reload"):
        logins.label_login(d, "grind", "two", old)


def test_an_account_label_names_a_live_key_and_an_empty_entry_leaves_accounts():
    d = _data()
    assert "labelled 'Paul K'" in logins.label_account(d, "claude-code:paul-k", "Paul K")
    assert "labelled 'own'" in logins.label_account(d, "claude-code:api", "own")  # a derived key is an account too
    assert "label cleared" in logins.label_account(d, "claude-code:api", None)
    assert "claude-code:api" not in d["accounts"]
    with pytest.raises(logins.LoginError, match="no account claude-code:nobody"):
        logins.label_account(d, "claude-code:nobody", "x")


def _rules(**kw):
    return {"default_home": False, "spends": True, "families": ["opus", "sonnet"]} | kw


def test_settings_follow_the_profile_rules():
    d = _data()
    ok = logins.set_setting
    with pytest.raises(logins.LoginError, match="belong to a metered login"):
        ok(d, "api", "prices", {"input": 3}, **_rules())
    assert ok(d, "api", "billing", "metered", **_rules()) == "claude-code:api billing set"
    assert ok(d, "api", "prices", {"input": 3, "output": 15}, **_rules()) == "claude-code:api prices set"
    assert d["logins"]["claude-code:api"]["prices"] == {"input": 3.0, "output": 15.0}
    for bad, words in (({"tokens": 1}, "not a token kind"), ({"input": -1}, "price per million"), ([1], "a mapping")):
        with pytest.raises(logins.LoginError, match=words):
            ok(d, "api", "prices", bad, **_rules())
    with pytest.raises(logins.LoginError, match="clear them"):
        ok(d, "api", "billing", "subscription", **_rules())
    with pytest.raises(logins.LoginError, match="clear them"):
        ok(d, "api", "billing", "", **_rules())
    with pytest.raises(logins.LoginError, match="default home"):
        ok(d, "claude-code:paul", "billing", "metered", **_rules(default_home=True))
    d["logins"]["claude-code:other"] = {"folder": "/h/.claude-grind", "account": "claude-code:someone"}
    with pytest.raises(logins.LoginError, match="shares its folder with claude-code:other, another account"):
        ok(d, "grind", "billing", "metered", **_rules())
    del d["logins"]["claude-code:other"]
    with pytest.raises(logins.LoginError, match="not a login's setting"):
        ok(d, "grind", "bogus", "", **_rules())  # an unknown key is refused before a clear
    with pytest.raises(logins.LoginError, match="reports no spend"):
        ok(d, "grind", "billing", "metered", **_rules(spends=False))
    with pytest.raises(logins.LoginError, match="subscription, not 'free'|subscription or metered, not 'free'"):
        ok(d, "grind", "billing", "free", **_rules())
    assert ok(d, "grind", "extra_args", ["--x"], **_rules()) == "claude-code:grind extra_args set"
    with pytest.raises(logins.LoginError, match="list of arguments"):
        ok(d, "grind", "unattended_args", "--x", **_rules())
    assert ok(d, "grind", "permission_wait", 600, **_rules()) == "claude-code:grind permission_wait set"
    for bad in (-1, True, "600"):
        with pytest.raises(logins.LoginError, match="seconds"):
            ok(d, "grind", "permission_wait", bad, **_rules())
    assert ok(d, "grind", "pin", "sonnet", **_rules()) == "claude-code:grind pin set"
    with pytest.raises(logins.LoginError, match="not a family"):
        ok(d, "grind", "pin", "haiku", **_rules())
    with pytest.raises(logins.LoginError, match="no model families read yet"):
        ok(d, "grind", "pin", "sonnet", **_rules(families=None))
    assert ok(d, "grind", "pin", None, **_rules()) == "claude-code:grind pin cleared"
    assert "pin" not in d["logins"]["claude-code:grind"]
    with pytest.raises(logins.LoginError, match="not a login's setting"):
        ok(d, "grind", "folder", "/x", **_rules())


def test_naming_an_account_takes_a_key_or_a_name_and_refuses_a_retired_name():
    d = _data()
    assert logins.join(d, "api", "work") == "claude-code:api joined claude-code:work"
    assert d["logins"]["claude-code:api"]["account"] == "claude-code:work"
    assert logins.join(d, "api", "claude-code:api") == "claude-code:api joined claude-code:api"
    assert "account" not in d["logins"]["claude-code:api"]  # its own derived key is never written
    with pytest.raises(logins.LoginError, match="under claude-code:api already"):
        logins.join(d, "api", "api")
    with pytest.raises(logins.LoginError, match="an account of gemini"):
        logins.join(d, "api", "gemini:x")
    with pytest.raises(logins.LoginError, match="not an account name"):
        logins.join(d, "api", "a b")
    d["forgotten"]["claude-code:old"] = {"folder": "/o", "account": "claude-code:gone"}
    with pytest.raises(logins.LoginError, match="forgotten account's key"):
        logins.join(d, "api", "gone")
    with pytest.raises(logins.LoginError, match="forgotten account's key"):
        logins.join(d, "api", "held", reserve_keys=["claude-code:held"])  # a reserve with no login retires it too
    assert logins.join(d, "api", "claude-code:gone") == "claude-code:api joined claude-code:gone"  # rejoined
    d["accounts"]["claude-code:gone"] = {"label": "old"}
    logins.join(d, "api", "work")
    assert "claude-code:gone" not in d["accounts"]  # its last login left it: its entry leaves too


def test_naming_an_account_is_refused_where_the_matches_would_disagree():
    d = _data()
    a, b = "claude-code\0a", "claude-code\0b"
    m = {"claude-code:paul": a, "claude-code:grind": a, "claude-code:api": b}
    with pytest.raises(logins.LoginError, match="under claude-code:paul-k and reads another account"):
        logins.join(d, "api", "paul-k", matches=m)
    m["claude-code:api"] = a
    with pytest.raises(logins.LoginError, match="reads the same account as claude-code:api"):
        logins.join(d, "api", "work", matches=m)
    assert logins.join(d, "api", "paul-k", matches=m) == "claude-code:api joined claude-code:paul-k"


def test_forget_moves_a_login_to_forgotten_and_its_last_account_leaves():
    d = _data()
    with pytest.raises(logins.LoginError, match="while ao-x-w use it"):
        logins.forget(d, "grind", in_use=["ao-x-w"])
    assert logins.forget(d, "grind") == "claude-code:grind forgotten"
    assert d["forgotten"]["claude-code:grind"] == {"folder": "/h/.claude-grind", "account": "claude-code:paul-k"}
    assert "claude-code:paul-k" in d["accounts"]  # another login is still under it
    logins.forget(d, "claude-code:paul")
    assert "claude-code:paul-k" not in d["accounts"]
    assert "claude-code:paul-k" in logins.retired(d)


def test_the_cli_calls_each_verb(monkeypatch, capsys):
    from shiftlead import cli

    asked = []
    monkeypatch.setattr(cli, "call_sync", lambda m, **k: asked.append((m, k)) or {"change": f"{m} done"})
    p = cli.build_parser()
    for argv in (
        ["login", "label", "grind", "work laptop"],
        ["login", "label", "grind"],
        ["account", "label", "claude-code:paul-k", "Paul"],
        ["login", "account", "api", "work"],
        ["login", "set", "api", "prices", "{input: 3, output: 15}"],
        ["login", "set", "api", "pin", ""],
        ["login", "note", "api", "the", "key", "account"],
        ["login", "forget", "api"],
    ):
        a = p.parse_args(argv)
        assert a.fn(a) == 0, argv
    assert asked == [
        ("login_label", {"login": "grind", "label": "work laptop"}),
        ("login_label", {"login": "grind", "label": None}),
        ("account_label", {"key": "claude-code:paul-k", "label": "Paul"}),
        ("login_account", {"login": "api", "account": "work"}),
        ("login_set", {"login": "api", "key": "prices", "value": {"input": 3, "output": 15}}),
        ("login_set", {"login": "api", "key": "pin", "value": None}),
        ("login_note", {"login": "api", "text": "the key account"}),
        ("login_forget", {"login": "api"}),
    ]
    assert "login_forget done" in capsys.readouterr().out


@pytest.mark.integration
async def test_the_verbs_are_the_persons_and_refused_before_the_switch(agent, tmp_path):
    from conftest import park_ticks

    from sessionorc import paths
    from sessionorc.client import AgentError, LocalClient

    await park_ticks(agent)
    calls = {
        "login_label": {"login": "grind", "label": "x"},
        "account_label": {"key": "claude-code:paul-k", "label": "x"},
        "login_note": {"login": "grind", "text": "x"},
        "login_set": {"login": "grind", "key": "permission_wait", "value": 60},
        "login_account": {"login": "grind", "account": "work"},
        "login_forget": {"login": "grind"},
        "login_shell": {"login": "grind"},
    }
    async with LocalClient() as c:
        for m, k in calls.items():
            with pytest.raises(AgentError, match="no logins until the switch-over"):
                await c.call(m, **k)
        logins.save(_data(), "fixture", paths.home())
        assert (await c.call("login_set", login="grind", key="permission_wait", value=60))["change"] == (
            "claude-code:grind permission_wait set"
        )
        await c.call("login_label", login="grind", label="work laptop")
        await c.call("account_label", key="claude-code:paul-k", label="Paul K")
        on_disk = yaml.safe_load(logins.path(paths.home()).read_text())
        assert on_disk["logins"]["claude-code:grind"] == {
            "folder": "/h/.claude-grind",
            "account": "claude-code:paul-k",
            "label": "work laptop",
            "permission_wait": 60,
        }
        assert on_disk["accounts"]["claude-code:paul-k"] == {"label": "Paul K"}
        assert agent._tools_kept is None  # a write drops the kept read: the page reads afresh
        agent._tools_kept = {
            "tools": [
                {
                    "adapter": "claude-code",
                    "logins": [{"name": "grind", "account": "k"}],
                    "accounts": [{"key": "k", "models": {"families": ["sonnet"]}}],
                }
            ]
        }
        await c.call("login_note", login="grind", text="x")  # drops the kept read again
        kept = agent._tools_kept
        agent.rpc_tools = lambda: _reread(agent, kept)
        assert (await c.call("login_set", login="grind", key="pin", value="sonnet"))["change"].endswith("pin set")
        async with LocalClient(caller="ao-repo-worker") as w:
            for m, k in calls.items():
                with pytest.raises(AgentError, match="ao-repo-worker cannot"):
                    await w.call(m, **k)
        assert (await c.call("login_forget", login="grind"))["change"] == "claude-code:grind forgotten"
        assert "claude-code:grind" in yaml.safe_load(logins.path(paths.home()).read_text())["forgotten"]


async def _reread(agent, kept):
    agent._tools_kept = {
        "tools": [
            {
                "adapter": "claude-code",
                "logins": [{"name": "grind", "account": "k"}],
                "accounts": [{"key": "k", "models": {"families": ["sonnet"]}}],
            }
        ]
    }
    return agent._tools_kept
