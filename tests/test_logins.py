"""A host's logins (design §4.2b *Where it lives*, *Matching across a restart*, *A login's state*, TD-1974): the
file, its names and versions, retired keys, the settling of a pass of reads, and the read's login tree."""

from __future__ import annotations

import pytest
import yaml

from sessionorc import adapters, defs, logins, tools


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
    (tmp_path / "logins.yml").write_text("logins: [\n")
    with pytest.raises(logins.LoginError):
        logins.load(tmp_path)


def test_a_write_is_committed_once_the_file_is_tracked(tmp_path, monkeypatch):
    monkeypatch.setattr(defs, "TRACKED", (*defs.TRACKED, "logins.yml"))
    monkeypatch.setattr(defs, "IGNORE", defs.IGNORE + "!logins.yml\n")
    assert defs.init(tmp_path)
    assert logins.save(logins.empty(), "first", tmp_path) is True
    log = defs._git(tmp_path, "log", "-1", "--format=%s").stdout.strip()
    assert log == "logins: first"


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
    assert mem.last == {"a": "x", "b": "x"} and mem.owner == {"x": "t:p"}


def test_a_match_another_account_has_marks_the_incoming_login_alone():
    mem = logins.Memory()
    logins.settle({"a": "t:p"}, {"a": "x"}, mem)
    s = logins.settle({"a": "t:p", "b": "t:q"}, {"a": "x", "b": "x"}, mem)
    assert s.mismatch == {"b"}


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
