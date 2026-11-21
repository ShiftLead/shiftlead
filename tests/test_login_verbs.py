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
    for bad, words in (
        ({"tokens": 1}, "not a token kind"),
        ({"input": -1}, "price per million"),
        ({"input": float("nan")}, "price per million"),
        ({"input": float("inf")}, "price per million"),
        ([1], "a mapping"),
    ):
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


def test_a_join_keeps_a_metered_logins_folder_its_accounts_alone():
    """§4.2a: a login sharing a metered login's folder never moves to another account, nor the metered one off its
    sharers' account; a folder shared by subscription logins alone moves freely."""
    d = _data()
    d["logins"]["claude-code:api2"] = {"folder": "/h/.claude-api"}  # shares api's folder, under its own key
    logins.join(d, "api2", "claude-code:api")
    assert logins.set_setting(d, "api", "billing", "metered", **_rules()) == "claude-code:api billing set"
    with pytest.raises(logins.LoginError, match="claude-code:api is metered"):
        logins.join(d, "api2", "work")  # the sharer leaves the metered login's account
    with pytest.raises(logins.LoginError, match="claude-code:api is metered"):
        logins.join(d, "api", "work")  # the metered login leaves its sharer's account
    logins.set_setting(d, "api", "billing", None, **_rules())
    assert logins.join(d, "api2", "work") == "claude-code:api2 joined claude-code:work"


def test_a_join_keeps_a_pin_its_new_account_offers_and_clears_any_other():
    fam = {"claude-code:paul-k": ["opus", "sonnet"], "claude-code:other": ["haiku"]}.get
    d = _data()
    d["logins"]["claude-code:api"]["pin"] = "sonnet"
    assert logins.join(d, "api", "claude-code:paul-k", families=fam) == "claude-code:api joined claude-code:paul-k"
    assert d["logins"]["claude-code:api"]["pin"] == "sonnet"
    got = logins.join(d, "api", "other", families=fam)
    assert (
        got == "claude-code:api joined claude-code:other; its pin sonnet cleared, as claude-code:other offers no sonnet"
    )
    assert "pin" not in d["logins"]["claude-code:api"]
    d["logins"]["claude-code:api"]["pin"] = "haiku"
    got = logins.join(d, "api", "fresh", families=fam)  # a new key: no read can have its families
    assert got.endswith("as claude-code:fresh is a new account no read has yet: pin it once it is signed in")
    assert "pin" not in d["logins"]["claude-code:api"]
    d["logins"]["claude-code:grind"]["pin"] = "opus"
    got = logins.join(d, "grind", "claude-code:fresh", families=fam)  # a live account whose families are unread
    assert got.endswith("its pin opus cleared, as claude-code:fresh's families are not read yet: Check again, then pin")


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


def _same(a, b):
    return str(a) == str(b)


def test_add_names_a_folder_a_login_and_a_forgotten_folder_takes_back_its_name():
    from pathlib import Path

    d = _data()
    kw = {"tools": ["claude-code", "gemini"], "same": _same}
    assert logins.add(d, "claude-code", Path("/h/.claude-new"), "new", **kw) == (
        "claude-code:new",
        "claude-code:new added",
    )
    assert d["logins"]["claude-code:new"] == {"folder": "/h/.claude-new"}
    with pytest.raises(logins.LoginError, match="claude-code:grind's folder already"):
        logins.add(d, "claude-code", Path("/h/.claude-grind"), "other", **kw)
    with pytest.raises(logins.LoginError, match="a login on this host already"):
        logins.add(d, "claude-code", Path("/h/.claude-x"), "grind", **kw)
    with pytest.raises(logins.LoginError, match="name the new login"):
        logins.add(d, "claude-code", Path("/h/.claude-x"), None, **kw)
    logins.forget(d, "grind")
    with pytest.raises(logins.LoginError, match="forgotten login's name"):
        logins.add(d, "claude-code", Path("/h/.claude-x"), "grind", **kw)  # never another folder's
    with pytest.raises(logins.LoginError, match="takes back its name, grind"):
        logins.add(d, "claude-code", Path("/h/.claude-grind"), "work", **kw)
    assert logins.add(d, "claude-code", Path("/h/.claude-grind"), None, **kw)[1] == (
        "claude-code:grind added back under claude-code:paul-k"
    )
    assert d["logins"]["claude-code:grind"]["account"] == "claude-code:paul-k" and not d["forgotten"]
    assert logins.add(d, "gemini", Path("/h/.claude-grind"), "grind", **kw)[0] == "gemini:grind"  # per tool
    logins.forget(d, "claude-code:grind")
    assert (
        logins.add(d, "claude-code", Path("/h/.claude-grind"), None, "grind", **kw)[1] == "claude-code:grind added back"
    )
    assert "account" not in d["logins"]["claude-code:grind"]  # its own account, named over the old one


def test_add_names_its_account_up_front_and_suggests_a_free_name():
    from pathlib import Path

    d = _data()
    kw = {"tools": ["claude-code"], "same": _same}
    assert (
        logins.add(d, "claude-code", Path("/a"), "a", "paul-k", **kw)[1]
        == "claude-code:a added under claude-code:paul-k"
    )
    with pytest.raises(logins.LoginError, match="an account of gemini"):
        logins.add(d, "claude-code", Path("/b"), "b", "gemini:x", **kw)
    logins.forget(d, "api")  # claude-code:api, an account of its own, is retired with it
    with pytest.raises(logins.LoginError, match="forgotten account's key"):
        logins.add(d, "claude-code", Path("/c"), "c", "api", **kw)
    assert logins.add(d, "claude-code", Path("/c"), "c", "claude-code:api", **kw)[1].endswith("under claude-code:api")
    assert logins.add(d, "claude-code", Path("/d"), None, suggested="paul", **kw)[0] == "claude-code:paul-2"
    assert logins.add(d, "claude-code", Path("/e"), "e", "claude-code:e", **kw)[1] == "claude-code:e added"


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
        ["login", "add", "claude-code", "--path", "~/.claude-w", "--name", "w", "--account", "paul-k"],
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
        ("login_add", {"tool": "claude-code", "path": "~/.claude-w", "name": "w", "account": "paul-k"}),
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
        "login_add": {"tool": "claude-code", "path": str(tmp_path / "made"), "name": "made"},
    }
    async with LocalClient() as c:
        for m, k in calls.items():
            with pytest.raises(AgentError, match="no logins until the switch-over"):
                await c.call(m, **k)
        assert not (tmp_path / "made").exists()  # refused before the switch: no folder made
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


@pytest.mark.integration
async def test_add_uses_a_home_makes_an_empty_folder_one_and_opens_its_shell(agent, tmp_path):
    from conftest import park_ticks

    from sessionorc import naming, paths
    from sessionorc.client import AgentError, LocalClient

    await park_ticks(agent)
    logins.save(_data(), "fixture", paths.home())
    home = tmp_path / "signed"
    home.mkdir()
    (home / ".credentials.json").write_text("{}")
    full = tmp_path / "full"
    full.mkdir()
    (full / "notes.txt").write_text("x")
    async with LocalClient() as c:
        got = await c.call("login_add", tool="claude-code", path=str(home), name="signed")
        assert got["change"] == "claude-code:signed added" and "shell" not in got  # a home: used, no shell
        made = tmp_path / "new"
        got = await c.call("login_add", tool="claude-code", path=str(made), name="fresh", account="paul-k")
        assert got["login"] == "claude-code:fresh" and made.is_dir() and made.stat().st_mode & 0o777 == 0o700
        assert got["shell"]["id"] == naming.tools_id("claude-code", "fresh")  # made: its shell opens for Sign in
        with pytest.raises(AgentError, match="neither a claude-code home nor an empty folder"):
            await c.call("login_add", tool="claude-code", path=str(full), name="full")
        with pytest.raises(AgentError, match="not a full path"):
            await c.call("login_add", tool="claude-code", path="rel/dir", name="rel")
        with pytest.raises(AgentError, match="no tool 'nope'"):
            await c.call("login_add", tool="nope", path=str(tmp_path / "n"), name="n")
        on_disk = yaml.safe_load(logins.path(paths.home()).read_text())["logins"]
        assert on_disk["claude-code:fresh"] == {"folder": str(made), "account": "claude-code:paul-k"}
        assert on_disk["claude-code:signed"] == {"folder": str(home)}


async def test_forget_and_naming_an_account_read_what_runs_and_what_is_retired(agent, tmp_path):
    from conftest import park_ticks

    from sessionorc import paths
    from sessionorc.client import AgentError, LocalClient
    from sessionorc.models import Session

    await park_ticks(agent)
    d = _data()
    d["logins"]["claude-code:api"]["pin"] = "sonnet"
    d["forgotten"]["claude-code:gone"] = {"folder": "/h/.claude-gone", "account": "claude-code:gone"}
    logins.save(d, "fixture", paths.home())
    (paths.home() / "settings.yml").write_text('usage_gate: {"claude-code:old": {week: 5}}\n')
    s = Session(id="ao-x-run", name="run", kind="interactive", adapter="claude-code", dir="/w/run")
    s.state, s.host, s.profile = "working", agent.host, "grind"
    agent.sessions[s.id] = s
    kept = {
        "tools": [
            {
                "adapter": "claude-code",
                "logins": [],
                "accounts": [{"key": "claude-code:paul-k", "models": {"families": ["opus"]}}],
            }
        ]
    }

    async def reread():  # a write drops the kept read: a join on a pinned login reads it afresh
        agent._tools_kept = kept
        return kept

    agent.rpc_tools = reread
    async with LocalClient() as c:
        with pytest.raises(AgentError, match="claude-code:grind cannot be forgotten while ao-x-run use it"):
            await c.call("login_forget", login="grind")
        s.state = "exited"  # ended: nothing runs on it
        assert (await c.call("login_forget", login="grind"))["change"] == "claude-code:grind forgotten"
        for name in ("old", "gone"):  # a reserve's key and a forgotten login's: retired, refused by name
            with pytest.raises(AgentError, match=f"claude-code:{name} is a forgotten account's key"):
                await c.call("login_account", login="api", account=name)
        agent._tools_memory.last.update({"claude-code:api": "a@x", "claude-code:paul": "b@x"})
        with pytest.raises(AgentError, match="claude-code:paul is under claude-code:paul-k and reads another account"):
            await c.call("login_account", login="api", account="paul-k")
        agent._tools_memory.last["claude-code:paul"] = "a@x"
        got = await c.call("login_account", login="api", account="paul-k")
        assert got["change"] == (
            "claude-code:api joined claude-code:paul-k; its pin sonnet cleared, as claude-code:paul-k offers no sonnet"
        )
        with pytest.raises(AgentError, match="claude-code:paul reads the same account as claude-code:api"):
            await c.call("login_account", login="api", account="claude-code:old")
        agent._tools_memory.last.clear()  # no match read: nothing to disagree with
        assert (await c.call("login_account", login="api", account="claude-code:old"))["change"] == (
            "claude-code:api joined claude-code:old"  # its full key rejoins it deliberately
        )


def test_a_reserve_moves_to_the_account_its_last_login_joins():
    from sessionorc import settings

    def gate(**g):
        return {"usage_gate": g}

    doc = gate(**{"claude-code:api": {"week": 5, "5h": {"per_day": 3}, "day": "$5"}})
    said = settings.move_reserve(doc, "claude-code:api", "claude-code:paul-k", False)
    assert doc == gate(**{"claude-code:paul-k": {"week": 5, "5h": {"per_day": 3}}})
    assert said == [
        "claude-code:paul-k takes claude-code:api's 5h reserve 3/day",
        "claude-code:api's day reserve $5 is dropped: claude-code:paul-k takes it nowhere, as it does not fit its "
        "billing",
        "claude-code:paul-k takes claude-code:api's week reserve 5",
    ]
    doc = gate(**{"a:x": {"week": 5, "day": 20}, "a:y": {"week": 10, "day": 7, "5h": 1}})
    said = settings.move_reserve(doc, "a:x", "a:y", False)  # the larger percent kept, the joined one's on a tie
    assert doc == gate(**{"a:y": {"week": 10, "day": 20, "5h": 1}})
    assert said == ["a:y takes a:x's day reserve 20 over its own 7", "a:y keeps its week reserve 10 over a:x's 5"]
    doc = gate(**{"a:x": {"day": "$5", "week": "$9"}, "a:y": {"day": "$8", "week": "2M tok"}})
    settings.move_reserve(doc, "a:x", "a:y", True)  # metered: the smaller amount, money before tokens
    assert doc == gate(**{"a:y": {"day": "$5", "week": "$9"}})
    doc = gate(**{"a:x": {"day": 5}})
    assert settings.move_reserve(doc, "a:x", "a:y", None) == [
        "a:x's day reserve 5 is dropped: a:y takes it nowhere, as its logins disagree on billing"
    ]
    assert doc == gate()
    assert settings.move_reserve(gate(**{"a:y": {"day": 5}}), "a:x", "a:y", False) is None  # none to move


@pytest.mark.integration
async def test_a_join_that_empties_an_account_moves_its_reserve(agent, tmp_path):
    from conftest import park_ticks

    from sessionorc import paths
    from sessionorc import settings as settings_mod
    from sessionorc.client import LocalClient

    await park_ticks(agent)
    logins.save(_data(), "fixture", paths.home())
    (paths.home() / "settings.yml").write_text(
        'usage_gate: {"claude-code:api": {week: 20, day: "$5"}, "claude-code:paul-k": {week: 10}}\n'
    )
    async with LocalClient() as c:
        got = await c.call("login_account", login="api", account="paul-k")
        assert got["change"] == (
            "claude-code:api joined claude-code:paul-k; claude-code:api's day reserve $5 is dropped: "
            "claude-code:paul-k takes it nowhere, as it does not fit its billing; claude-code:paul-k takes "
            "claude-code:api's week reserve 20 over its own 10"
        )
        assert settings_mod.read()["usage_gate"] == {"claude-code:paul-k": {"week": 20}}
        got = await c.call("login_account", login="grind", account="work")  # paul-k keeps paul and api: it stays
        assert got["change"] == "claude-code:grind joined claude-code:work"
        assert settings_mod.read()["usage_gate"] == {"claude-code:paul-k": {"week": 20}}
    import asyncio

    await asyncio.gather(*list(agent._bg))  # the move's push and commit, detached: done before the home is torn down
