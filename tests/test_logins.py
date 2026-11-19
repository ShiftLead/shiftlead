"""A host's logins (design §4.2b *Where it lives*, *Matching across a restart*, *A login's state*, TD-1974): the
file, its names and versions, retired keys, the settling of a pass of reads, and the read's login tree."""

from __future__ import annotations

import pytest
import yaml

from sessionorc import adapters, agent_common, defs, logins, tools


def test_names_follow_the_rules():
    assert logins.valid_name("claude-paul") and logins.valid_name("a_1") and logins.valid_name("x" * 24)
    for bad in ("", "-x", "_x", "x" * 25, "a:b", "a.b", "a@b", "a b", None):
        assert not logins.valid_name(bad), bad
    assert logins.split("claude-code:paul") == ("claude-code", "paul") and logins.key("t", "w") == "t:w"
    assert logins.name_of("Paul K") == "paul-k" and logins.name_of("@@") == ""
    assert logins.suggest("paul", []) == "paul" and logins.suggest("paul", ["paul", "paul-2"]) == "paul-3"
    assert len(logins.suggest("x" * 24, ["x" * 24])) <= 24


def test_a_name_is_unique_per_tool_and_its_tools_shell_id_on_the_host():
    data = logins.empty()
    data["logins"]["claude-code:paul"] = {"folder": "/f"}
    assert "already" in logins.name_taken(data, "claude-code", "paul")
    assert logins.name_taken(data, "grok", "paul") is None  # another tool's login may share the name
    assert "tools shell would be claude-code:paul's" in logins.name_taken(data, "claude-code", "Paul")
    assert "tools shell would be claude-code:paul's" in logins.name_taken(data, "claude", "code-paul")
    assert "install shell" in logins.name_taken(logins.empty(), "install", "grok", tools=["grok"])
    assert "not a login name" in logins.name_taken(data, "grok", "a:b")


def test_the_file_round_trips_and_an_unswitched_host_reads_none(tmp_path):
    assert logins.load(tmp_path) is None and not logins.switched(tmp_path)
    data = logins.empty()
    data["logins"]["t:w"] = {"folder": "/f", "label": None, "account": "t:paul"}
    data["accounts"]["t:paul"] = {"label": "work"}
    data["forgotten"]["t:old"] = {"folder": "/o", "account": "t:gone"}
    assert logins.save(data, "w added", tmp_path) is False  # not tracked before the switch-over: no commit
    raw = yaml.safe_load((tmp_path / "logins.yml").read_text())
    assert raw["logins"]["t:w"] == {"folder": "/f", "account": "t:paul"}  # an unset key is not written
    assert logins.load(tmp_path) == {
        "logins": {"t:w": {"folder": "/f", "account": "t:paul"}},
        "accounts": {"t:paul": {"label": "work"}},
        "forgotten": {"t:old": {"folder": "/o", "account": "t:gone"}},
    }
    for bad in ("logins: [\n", "logins:\n  t:a: x\n", "logins:\n  t:a: [1]\n", "- 1\n"):
        (tmp_path / "logins.yml").write_text(bad)
        with pytest.raises(logins.LoginError):
            logins.load(tmp_path)


def test_a_write_at_the_home_is_committed_as_logins(tmp_path):
    assert "logins.yml" in defs.TRACKED and "profiles.yml" in defs.TRACKED  # beside it until the switch-over
    assert "logins.yml" in agent_common.BACKUP_MEMBERS
    assert defs.init(tmp_path)
    assert logins.save(logins.empty(), "first", tmp_path) is True
    log = defs._git(tmp_path, "log", "-1", "--format=%s").stdout.strip()
    assert log == "logins: first"
    assert logins.save(logins.empty(), "again", tmp_path) is False  # nothing changed, nothing committed


def test_a_home_made_a_tree_before_logins_were_tracked_lets_the_file_in_on_its_write(tmp_path):
    assert defs.init(tmp_path)
    ignore = tmp_path / ".gitignore"
    ignore.write_text(ignore.read_text().replace("!logins.yml\n", ""))  # the ignore file an older home wrote
    defs._git(tmp_path, "commit", "-qam", "older home")
    assert logins.save({"accounts": {"t:paul": {"label": "work"}}}, "account t:paul", tmp_path) is True
    assert "!logins.yml" in ignore.read_text().splitlines()
    files = defs._git(tmp_path, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert sorted(files) == [".gitignore", "logins.yml"]


def test_a_write_on_a_node_commits_nothing(tmp_path):
    assert logins.save(logins.empty(), "first", tmp_path) is False  # a node's home is no tree
    assert (tmp_path / "logins.yml").exists() and not defs.is_tree(tmp_path)


def test_a_version_is_the_entry_s_hash_and_a_stale_one_is_refused():
    e = {"tool": "t", "folder": "/f"}
    v = logins.version(e)
    assert v == logins.version({**e, "note": None}) and v != logins.version({**e, "note": "x"})
    logins.check_version(e, v, "w")
    logins.check_version(e, None, "w")  # nothing sent: nothing to compare
    with pytest.raises(logins.LoginError, match="changed since this page read it"):
        logins.check_version({**e, "note": "x"}, v, "w")


def test_resolve_takes_a_name_or_tool_and_name_never_a_label():
    data = logins.empty()
    data["logins"]["t:w"] = {"folder": "/f", "label": "work"}
    assert logins.resolve(data, "w")[0] == "t:w" and logins.resolve(data, "t:w")[0] == "t:w"
    for ref in ("work", "u:w", "x"):
        with pytest.raises(logins.LoginError):
            logins.resolve(data, ref)
    data["logins"]["u:w"] = {"folder": "/g"}
    assert logins.resolve(data, "u:w")[0] == "u:w"
    with pytest.raises(logins.LoginError, match="say which, t:w or u:w"):
        logins.resolve(data, "w")  # a bare name two tools' logins share is refused, naming both


def test_a_retired_key_is_a_forgotten_or_reserved_key_no_live_login_names():
    data = logins.empty()
    data["logins"]["t:w"] = {"folder": "/f", "account": "t:paul"}
    data["logins"]["t:k"] = {"folder": "/k"}  # derived key t:k
    data["forgotten"]["t:old"] = {"folder": "/o", "account": "t:gone"}
    data["forgotten"]["t:w2"] = {"folder": "/o2", "account": "t:paul"}
    assert logins.retired(data, ["t:orphan", "t:k"]) == {"t:gone", "t:orphan"}


# ---- the settle ----


def test_a_first_match_joins_its_stored_account():
    mem = logins.Memory()
    s = logins.settle({"a": "t:p", "b": "t:p"}, {"a": "x", "b": "x"}, mem)
    assert s.account == {"a": "t:p", "b": "t:p"} and not s.moves and not s.mismatch and not s.name_account
    assert mem.last == {"a": "x", "b": "x"} and not mem.unnamed


def test_a_match_another_account_has_marks_the_incoming_login_alone():
    mem = logins.Memory()
    logins.settle({"a": "t:p"}, {"a": "x"}, mem)
    s = logins.settle({"a": "t:p", "b": "t:q"}, {"a": "x", "b": "x"}, mem)
    assert s.mismatch == {"b"}


def test_which_account_has_a_match_is_read_from_this_pass_not_the_run_s_history():
    mem = logins.Memory()
    logins.settle({"a": "t:p"}, {"a": "x"}, mem)
    logins.settle({"a": "t:p"}, {"a": "y"}, mem)  # a moved on: no p login reads x any more
    s = logins.settle({"a": "t:p", "b": "t:q"}, {"a": "y", "b": "x"}, mem)
    assert not s.mismatch and s.account["b"] == "t:q"


def test_a_match_established_on_two_accounts_marks_every_reader():
    mem = logins.Memory()
    logins.settle({"a": "t:p", "b": "t:q"}, {"a": "x", "b": "y"}, mem)
    logins.settle({"a": "t:p", "b": "t:q"}, {"a": "x", "b": "y"}, mem)
    s = logins.settle({"a": "t:p", "b": "t:q", "c": None}, {"a": "x", "b": "y", "c": "x"}, mem)
    assert s.moves == {"c": "t:p"} and not s.mismatch


def test_a_stored_account_whose_logins_read_two_matches_marks_all_of_them():
    s = logins.settle({"a": "t:p", "b": "t:p", "c": "t:q"}, {"a": "x", "b": "y", "c": "z"}, logins.Memory())
    assert s.mismatch == {"a", "b"}


def test_two_accounts_reading_one_match_at_start_mark_every_reader():
    s = logins.settle({"a": "t:p", "b": "t:q"}, {"a": "x", "b": "x"}, logins.Memory())
    assert s.mismatch == {"a", "b"}


def test_a_change_within_the_run_moves_the_login_or_asks_for_a_name():
    mem = logins.Memory()
    logins.settle({"a": "t:p", "b": "t:q"}, {"a": "x", "b": "y"}, mem)
    s = logins.settle({"a": "t:p", "b": "t:q"}, {"a": "y", "b": "y"}, mem)  # a signed in as b's account
    assert s.moves == {"a": "t:q"} and s.account["a"] == "t:q" and not s.mismatch
    s = logins.settle({"a": "t:q", "b": "t:q"}, {"a": "z", "b": "y"}, mem)  # then as an account none has
    assert s.name_account == {"a"} and not s.moves
    for _ in range(2):  # it stays so pass after pass, never rejoining its stored account unmarked
        s = logins.settle({"a": "t:q", "b": "t:q"}, {"a": "z", "b": "y"}, mem)
        assert s.name_account == {"a"} and s.account["a"] is None and not s.mismatch and not s.moves
    s = logins.settle({"a": "t:r", "b": "t:q"}, {"a": "z", "b": "y"}, mem)  # the person names it
    assert not s.name_account and s.account["a"] == "t:r" and not s.mismatch


def test_a_new_login_joins_an_account_with_its_match_or_waits_for_a_name():
    mem = logins.Memory()
    logins.settle({"a": "t:p"}, {"a": "x"}, mem)
    s = logins.settle({"a": "t:p", "n": None, "m": None}, {"a": "x", "n": "x", "m": "w"}, mem)
    assert s.moves == {"n": "t:p"} and s.name_account == {"m"}


def test_a_signed_out_login_keeps_its_stored_account():
    s = logins.settle({"a": "t:p", "k": None}, {"a": None, "k": None}, logins.Memory())
    assert s.account == {"a": "t:p", "k": None} and not s.moves


def test_states_follow_the_table():
    ident = {"match": "m"}
    assert logins.state(ident, True) == "signed_in" and logins.state(ident, None) == "signed_in"
    assert logins.state(ident, False) == "sign_in_again"
    assert logins.state(None, False) == "not_signed_in" and logins.state(None, None) == "not_signed_in"
    assert logins.state(None, True) == "signed_in"


# ---- the read's login tree ----


class _Tool:
    """An agent adapter whose identity and credentials are set per folder."""

    implements = frozenset({"find", "identity", "credentials_ok", "models"})

    def __init__(self, name, default, by_folder):
        self.name, self.label, self._default, self.by_folder = name, name, default, by_folder

    def find(self):
        return f"/bin/{self.name}"

    def default_home(self, env):
        return self._default

    def tool_version(self, env):
        return "1.0"

    def identity(self, home, salt):
        got = self.by_folder.get(str(home), (None, None))[0]
        return dict(got) if got else None

    def credentials_ok(self, home):
        return self.by_folder.get(str(home), (None, None))[1]

    def models(self, home, plan):
        return {"families": ["big", "small"], "default": None, "unconfirmed": plan is None}


def _host(monkeypatch, tool):
    monkeypatch.setattr(adapters, "names", lambda: [tool.name])
    monkeypatch.setattr(adapters, "has_agent", lambda n: True)
    monkeypatch.setattr(adapters, "get", lambda n: tool)
    monkeypatch.setattr(adapters, "known_tools", lambda: [])


def test_a_switched_host_draws_its_logins_in_each_state(monkeypatch, tmp_path):
    f = {n: str(tmp_path / n) for n in ("work", "again", "out", "key", "new", "default")}
    sub = {"match": "SECRETMATCH", "display": "Paul", "plan": "Max", "billing": "subscription"}
    tool = _Tool(
        "t",
        tmp_path / "default",
        {
            f["work"]: (sub, True),
            f["again"]: (sub, False),
            f["out"]: (None, False),
            f["key"]: (None, True),
            f["new"]: ({"match": "OTHER", "plan": None}, True),
            f["default"]: (sub, True),
        },
    )
    _host(monkeypatch, tool)
    data = logins.empty()
    for n in ("work", "again", "out", "key", "new"):
        data["logins"][f"t:{n}"] = {"folder": f[n]}
    for n in ("work", "again", "out"):
        data["logins"][f"t:{n}"]["account"] = "t:paul"
    data["logins"]["t:work"].update(billing="metered", pin="small", note="the main one", label="work laptop")
    data["accounts"]["t:paul"] = {"label": "Paul's"}
    logins.save(data, "fixture", tmp_path)
    r = tools.read(b"s" * 32, env={}, home=tmp_path, memory=logins.Memory())
    assert r["switched"] is True
    [card] = r["tools"]
    got = {lg["name"]: lg for lg in card["logins"]}
    assert {n: (lg["state"], lg["account"]) for n, lg in got.items()} == {
        "work": ("signed_in", "t:paul"),
        "again": ("sign_in_again", "t:paul"),
        "out": ("not_signed_in", "t:paul"),
        "key": ("signed_in", "t:key"),
        "new": ("name_account", None),
    }
    w = got["work"]
    assert w["label"] == "work laptop" and w["pin"] == "small" and w["note"] == "the main one"
    assert w["warnings"] == ["billing_mismatch"] and w["version"] == logins.version(data["logins"]["t:work"])
    # its Settings but the pin, the Tools page's form values; unset ones null
    assert w["settings"] == {
        "billing": "metered", "prices": None, "extra_args": None, "unattended_args": None, "permission_wait": None
    }  # fmt: skip
    accts = {a["key"]: a for a in card["accounts"]}
    assert set(accts) == {"t:paul", "t:key"}
    assert accts["t:paul"]["label"] == "Paul's" and accts["t:paul"]["plan"] == "Max"
    assert accts["t:paul"]["billing"] == "metered" and accts["t:paul"]["models"]["families"] == ["big", "small"]
    assert card["found"] == [{"folder": f["default"], "own_home": False}]  # signed in and no login yet
    assert "SECRETMATCH" not in repr(r) and "OTHER" not in repr(r) and "Paul'" not in repr(r).replace("Paul's", "")


def test_a_login_that_joins_an_account_is_written(monkeypatch, tmp_path):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    ident = {"match": "M", "plan": "Pro"}
    _host(monkeypatch, _Tool("t", tmp_path / "none", {a: (ident, True), b: (ident, True)}))
    data = logins.empty()
    data["logins"]["t:a"] = {"folder": a, "account": "t:paul"}
    data["logins"]["t:b"] = {"folder": b}
    logins.save(data, "fixture", tmp_path)
    mem = logins.Memory()
    tools.read(b"s" * 32, env={}, home=tmp_path, memory=mem)
    assert logins.load(tmp_path)["logins"]["t:b"]["account"] == "t:paul"
    assert "M" not in (tmp_path / "logins.yml").read_text().split()  # no match is ever written


def test_a_login_on_the_default_home_hides_the_found_row(monkeypatch, tmp_path):
    d = str(tmp_path / "default")
    _host(monkeypatch, _Tool("t", tmp_path / "default", {d: ({"match": "M"}, True)}))
    data = logins.empty()
    data["logins"]["t:mine"] = {"folder": d, "account": "t:paul"}
    logins.save(data, "fixture", tmp_path)
    [card] = tools.read(b"s" * 32, env={}, home=tmp_path)["tools"]
    assert card["found"] == [] and [lg["name"] for lg in card["logins"]] == ["mine"]


def test_a_join_never_overwrites_a_write_made_while_the_pass_read(monkeypatch, tmp_path):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    ident = {"match": "M"}

    class _Slow(_Tool):
        def identity(self, home, salt):  # the person writes a note while the pass is reading
            if str(home) == b:
                logins.update(lambda d: d["logins"]["t:a"].update(note="mine") or "a note", tmp_path)
            return super().identity(home, salt)

    _host(monkeypatch, _Slow("t", tmp_path / "none", {a: (ident, True), b: (ident, True)}))
    data = logins.empty()
    data["logins"]["t:a"] = {"folder": a, "account": "t:paul"}
    data["logins"]["t:b"] = {"folder": b}
    logins.save(data, "fixture", tmp_path)
    tools.read(b"s" * 32, env={}, home=tmp_path, memory=logins.Memory())
    now = logins.load(tmp_path)["logins"]
    assert now["t:a"]["note"] == "mine" and now["t:b"]["account"] == "t:paul"


def test_a_poll_moves_a_login_signed_in_since_the_read_and_probes_no_version(monkeypatch, tmp_path):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    tool = _Tool("t", tmp_path / "none", {a: ({"match": "M", "plan": "Pro"}, True), b: (None, False)})
    _host(monkeypatch, tool)
    data = logins.empty()
    data["logins"]["t:a"] = {"folder": a, "account": "t:paul"}
    data["logins"]["t:b"] = {"folder": b}
    logins.save(data, "fixture", tmp_path)
    mem = logins.Memory()
    kept = tools.read(b"s" * 32, env={}, home=tmp_path, memory=mem)
    assert {lg["name"]: lg["state"] for lg in kept["tools"][0]["logins"]} == {"a": "signed_in", "b": "not_signed_in"}

    def no_probe(env):
        raise AssertionError("a poll probes no version")

    tool.tool_version = no_probe
    tool.find = lambda: (_ for _ in ()).throw(AssertionError("a poll finds nothing"))
    tool.by_folder[b] = ({"match": "M", "plan": "Pro"}, True)  # the person signed in in the tools shell
    got = tools.repoll(kept, b"s" * 32, home=tmp_path, memory=mem)
    [card] = got["tools"]
    assert {lg["name"]: (lg["state"], lg["account"]) for lg in card["logins"]} == {
        "a": ("signed_in", "t:paul"),
        "b": ("signed_in", "t:paul"),
    }
    assert [x["key"] for x in card["accounts"]] == ["t:paul"] and card["version"] == kept["tools"][0]["version"]
    assert logins.load(tmp_path)["logins"]["t:b"]["account"] == "t:paul"
    assert [lg["name"] for lg in kept["tools"][0]["logins"]] == ["a", "b"]  # the kept read is not edited in place


def test_a_poll_drops_a_found_row_whose_folder_became_a_login(monkeypatch, tmp_path):
    d = str(tmp_path / "default")
    _host(monkeypatch, _Tool("t", tmp_path / "default", {d: ({"match": "M"}, True)}))
    logins.save(logins.empty(), "fixture", tmp_path)
    kept = tools.read(b"s" * 32, env={}, home=tmp_path, memory=logins.Memory())
    assert kept["tools"][0]["found"] == [{"folder": d, "own_home": False}]
    logins.update(lambda data: data["logins"].update({"t:mine": {"folder": d}}) or "a login", tmp_path)
    [card] = tools.repoll(kept, b"s" * 32, home=tmp_path, memory=logins.Memory())["tools"]
    assert card["found"] == [] and [lg["name"] for lg in card["logins"]] == ["mine"]
    assert kept["tools"][0]["found"]  # the kept read is not edited in place


async def test_a_poll_runs_only_while_a_login_s_tools_shell_is_open(monkeypatch):
    import asyncio

    from sessionorc import agent as agent_mod

    ag = agent_mod.HostAgent.__new__(agent_mod.HostAgent)
    ag._tools_poll_task, ag._tools_polled_at = None, -1e9
    ag._tools_lock, ag._tools_salt, ag._tools_memory = asyncio.Lock(), b"s" * 32, logins.Memory()
    ag._tools_was_switched = True
    ag._tools_kept, ag._tools_gen, ag._tools_poll_failing = {"switched": True, "tools": []}, 0, False
    calls = []
    monkeypatch.setattr(tools, "repoll", lambda kept, salt, memory=None: calls.append(kept) or {**kept, "polled": 1})
    pane = type("P", (), {"dead": False})()
    dead = type("P", (), {"dead": True})()
    for panes in ({}, {"ao--tools-install-t": pane}, {"ao--tools-t-paul": dead}, {"ao-repo-w": pane}):
        ag._tools_poll_due(panes)
        assert ag._tools_poll_task is None, panes  # no login's tools shell open: no poll
    ag._tools_poll_due({"ao--tools-t-paul": pane})
    await ag._tools_poll_task
    assert len(calls) == 1 and ag._tools_kept["polled"] == 1
    ag._tools_poll_due({"ao--tools-t-paul": pane})
    assert ag._tools_poll_task.done() and len(calls) == 1  # within the interval: no second pass
    ag._tools_polled_at = -1e9
    async with ag._tools_lock:  # a full read in flight: the poll yields to it
        ag._tools_poll_due({"ao--tools-t-paul": pane})
        await ag._tools_poll_task
    assert len(calls) == 1
    ag._tools_polled_at, ag._tools_kept = -1e9, {"switched": False, "tools": []}
    ag._tools_poll_due({"ao--tools-t-paul": pane})
    assert ag._tools_poll_task.done() and len(calls) == 1  # an unswitched host polls no logins


async def test_a_read_begun_before_a_logins_write_is_never_kept_and_its_memory_is_a_copy(monkeypatch, tmp_path):
    """A poll in flight when a login write lands settled the file as it was: the write's cleared read stays cleared,
    and the memory it settled is not kept; the pass settles a copy, never the memory the loop reads."""
    import asyncio
    import threading

    from sessionorc import agent as agent_mod

    ag = agent_mod.HostAgent.__new__(agent_mod.HostAgent)
    ag._tools_poll_task, ag._tools_polled_at = None, -1e9
    ag._tools_lock, ag._tools_salt, ag._tools_memory = asyncio.Lock(), b"s" * 32, logins.Memory()
    ag._tools_was_switched = True
    ag._tools_kept, ag._tools_gen, ag._tools_poll_failing = {"switched": True, "tools": [], "label": "old"}, 0, False
    loop_memory = ag._tools_memory
    started, release = threading.Event(), threading.Event()

    def repoll(kept, salt, memory=None):
        assert memory is not loop_memory
        memory.last["claude-code:paul"] = "m1"
        started.set()
        release.wait(5)
        return {**kept, "polled": 1}

    monkeypatch.setattr(tools, "repoll", repoll)
    monkeypatch.setattr(logins, "update", lambda edit, home=None: "claude-code:paul labelled 'new'")
    ag._tools_poll_due({"ao--tools-t-paul": type("P", (), {"dead": False})()})
    await asyncio.to_thread(started.wait, 5)
    assert await ag._login_write(lambda d: "x") == {"change": "claude-code:paul labelled 'new'"}
    release.set()
    await ag._tools_poll_task
    assert ag._tools_kept is None and ag._tools_memory is loop_memory and not loop_memory.last
    ag._tools_kept = {"switched": True, "tools": []}
    ag._tools_polled_at = -1e9
    monkeypatch.setattr(tools, "repoll", lambda kept, salt, memory=None: memory.last.update(x="m") or {**kept, "p": 2})
    ag._tools_poll_due({"ao--tools-t-paul": type("P", (), {"dead": False})()})
    await ag._tools_poll_task
    assert ag._tools_kept["p"] == 2 and ag._tools_memory.last == {"x": "m"}  # no write between: both kept


async def test_a_logins_write_never_stops_the_poll_its_next_pass_reads_in_full(monkeypatch):
    """§4.2b *The tools shell*: the poll runs while the shell is open. A write clears the kept read; the next pass is a
    full read, and the passes after it repoll. Before the run's first read, no pass at all."""
    import asyncio

    from sessionorc import agent as agent_mod

    ag = agent_mod.HostAgent.__new__(agent_mod.HostAgent)
    ag._tools_poll_task, ag._tools_polled_at = None, -1e9
    ag._tools_lock, ag._tools_salt, ag._tools_memory = asyncio.Lock(), b"s" * 32, logins.Memory()
    ag._tools_kept, ag._tools_gen, ag._tools_poll_failing, ag._tools_was_switched = None, 0, False, False
    reads, polls = [], []
    monkeypatch.setattr(
        tools, "read", lambda salt, env=None, home=None, memory=None: reads.append(1) or {"switched": True}
    )
    monkeypatch.setattr(tools, "repoll", lambda kept, salt, memory=None: polls.append(1) or {**kept, "p": 1})
    shell = {"ao--tools-t-paul": type("P", (), {"dead": False})()}
    ag._tools_poll_due(shell)
    assert ag._tools_poll_task is None  # before the run's first read: none
    await ag._tools_reread()
    monkeypatch.setattr(logins, "update", lambda edit, home=None: "noted")
    await ag._login_write(lambda d: "x")
    assert ag._tools_kept is None
    ag._tools_poll_due(shell)
    await ag._tools_poll_task
    assert len(reads) == 2 and not polls and ag._tools_kept == {"switched": True}  # the pass after a write: in full
    ag._tools_polled_at = -1e9
    ag._tools_poll_due(shell)
    await ag._tools_poll_task
    assert len(reads) == 2 and len(polls) == 1  # and repolls after it


async def test_a_poll_s_failing_full_read_is_logged_once_and_waits_longer(monkeypatch, caplog):
    import asyncio

    from sessionorc import agent as agent_mod

    ag = agent_mod.HostAgent.__new__(agent_mod.HostAgent)
    ag._tools_poll_task, ag._tools_polled_at = None, -1e9
    ag._tools_lock, ag._tools_salt, ag._tools_memory = asyncio.Lock(), b"s" * 32, logins.Memory()
    ag._tools_kept, ag._tools_gen, ag._tools_poll_failing, ag._tools_was_switched = None, 0, False, True
    reads = []

    def read(salt, env=None, home=None, memory=None):
        reads.append(1)
        raise OSError("gone")

    monkeypatch.setattr(tools, "read", read)
    shell = {"ao--tools-t-paul": type("P", (), {"dead": False})()}
    ag._tools_poll_due(shell)
    await ag._tools_poll_task
    ag._tools_poll_due(shell)
    assert ag._tools_poll_task.done() and len(reads) == 1  # 5 s on: the failed full read waits longer
    for _ in range(2):
        ag._tools_polled_at = -1e9
        ag._tools_poll_due(shell)
        await ag._tools_poll_task
    assert len(reads) == 3 and sum("tools read failed" in r.message for r in caplog.records) == 1
    ag._tools_was_switched = False  # an unswitched host's cleared read starts no pass
    ag._tools_polled_at = -1e9
    ag._tools_poll_due(shell)
    assert ag._tools_poll_task.done() and len(reads) == 3


async def test_a_failing_poll_is_logged_once_until_one_succeeds(monkeypatch, caplog):
    import asyncio

    from sessionorc import agent as agent_mod

    ag = agent_mod.HostAgent.__new__(agent_mod.HostAgent)
    ag._tools_poll_task, ag._tools_polled_at = None, -1e9
    ag._tools_lock, ag._tools_salt, ag._tools_memory = asyncio.Lock(), b"s" * 32, logins.Memory()
    ag._tools_was_switched = True
    ag._tools_kept, ag._tools_gen, ag._tools_poll_failing = {"switched": True, "tools": []}, 0, False
    ok = []

    def repoll(kept, salt, memory=None):
        if not ok:
            raise logins.LoginError("logins.yml is malformed")
        return {**kept, "p": 1}

    monkeypatch.setattr(tools, "repoll", repoll)
    for _ in range(3):
        await ag._tools_poll()
    assert sum("poll failed" in r.message for r in caplog.records) == 1
    ok.append(1)
    await ag._tools_poll()
    assert not ag._tools_poll_failing and ag._tools_kept["p"] == 1
    ok.clear()
    await ag._tools_poll()
    assert sum("poll failed" in r.message for r in caplog.records) == 2  # failing again after a success: said again


def test_update_refuses_an_unswitched_host_and_writes_nothing_for_no_change(tmp_path):
    with pytest.raises(logins.LoginError, match="switch-over"):
        logins.update(lambda d: "x", tmp_path)
    logins.save(logins.empty(), "first", tmp_path)
    before = (tmp_path / "logins.yml").stat().st_mtime_ns
    assert logins.update(lambda d: None, tmp_path) is None
    assert (tmp_path / "logins.yml").stat().st_mtime_ns == before
