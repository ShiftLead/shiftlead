"""TD-2279, design §4.2b **Names are fixed**, §4.9e *A record's `profile`*: a login's name is unique on its host across
every tool, a forgotten login's staying taken, so a record written under a login's bare name goes on resolving to that
login and its account after another tool's login is added, and again once it is forgotten and taken back."""

from __future__ import annotations

from pathlib import Path

import pytest

from sessionorc import logins
from shiftlead import profiles

TOOLS = ["claude-code", "gemini"]
LIVE = "grind is claude-code:grind's name on this host: a login's name is unique on its host"


def _same(a: Path, b: Path) -> bool:
    return a == b


def _home(tmp_path: Path) -> dict:
    d = logins.empty()
    d["logins"]["claude-code:grind"] = {"folder": "/h/.claude-grind", "account": "claude-code:acct-1"}
    logins.save(d, "fixture", tmp_path)
    return logins.load(tmp_path)


def _add(d: dict, tool: str, folder: str, name: str | None, **kw) -> tuple[str, str]:
    return logins.add(d, tool, Path(folder), name, tools=TOOLS, same=_same, **kw)


@pytest.mark.unit
def test_another_tools_live_name_is_refused_and_the_file_is_unchanged(tmp_path):
    d = _home(tmp_path)
    before = logins.path(tmp_path).read_text()
    with pytest.raises(logins.LoginError) as e:
        logins.update(lambda data: _add(data, "gemini", "/h/.gemini", "grind")[1], tmp_path)
    assert str(e.value) == LIVE
    assert logins.path(tmp_path).read_text() == before
    assert logins.name_holder(d, "gemini", "grind") == ("claude-code:grind", False)
    assert logins.name_holder(d, "claude-code", "grind") is None, "the same tool's own key is name_taken's"
    assert logins.name_holder(d, "gemini", "grind", skip="claude-code:grind") is None


@pytest.mark.unit
def test_another_tools_forgotten_name_is_refused_and_its_take_back_passes(tmp_path):
    d = _home(tmp_path)
    _add(d, "gemini", "/h/.gemini-old", "old")
    logins.forget(d, "gemini:old")
    assert logins.name_holder(d, "claude-code", "old") == ("gemini:old", True)
    with pytest.raises(logins.LoginError, match=r"^old is the forgotten login gemini:old's name, kept for its own"):
        _add(d, "claude-code", "/h/.claude-old", "old")
    assert _add(d, "gemini", "/h/.gemini-old", None)[1] == "gemini:old added back"


@pytest.mark.unit
def test_a_take_back_whose_name_another_tool_holds_is_refused():
    d = logins.empty()  # a hand-edited file: gemini:grind live beside a forgotten claude-code:grind
    d["logins"]["gemini:grind"] = {"folder": "/h/.gemini"}
    d["forgotten"]["claude-code:grind"] = {"folder": "/h/.claude-grind", "account": "claude-code:grind"}
    with pytest.raises(logins.LoginError, match="gemini:grind's name on this host"):
        _add(d, "claude-code", "/h/.claude-grind", None)


@pytest.mark.unit
def test_the_suggested_name_skips_another_tools_live_and_forgotten_names(tmp_path):
    d = _home(tmp_path)
    _add(d, "gemini", "/h/.gemini-x", "gemini-paul")
    logins.forget(d, "gemini:gemini-paul")
    assert _add(d, "claude-code", "/h/.claude-x", None, suggested="gemini-paul")[0] == "claude-code:gemini-paul-2"
    assert _add(d, "gemini", "/h/.gemini-y", None, suggested="grind")[0] == "gemini:grind-2"


@pytest.mark.unit
def test_a_record_written_as_the_bare_name_keeps_its_account(tmp_path):
    prof = tmp_path / "profiles.yml"
    _home(tmp_path)
    logins.update(lambda d: _add(d, "gemini", "/h/.gemini", "reader")[1], tmp_path)
    assert profiles.get("grind", prof).name == "grind"
    assert profiles.account_of("grind", "claude-code", prof) == "acct-1"
    logins.update(lambda d: logins.forget(d, "claude-code:grind"), tmp_path)
    with pytest.raises(KeyError):
        profiles.get("grind", prof)  # a forgotten login's records resolve to no login meanwhile
    with pytest.raises(logins.LoginError, match=r"^grind is the forgotten login claude-code:grind's name"):
        logins.update(lambda d: _add(d, "gemini", "/h/.gemini-g", "grind")[1], tmp_path)
    logins.update(lambda d: _add(d, "claude-code", "/h/.claude-grind", None)[1], tmp_path)
    assert profiles.account_of("grind", "claude-code", prof) == "acct-1", "taken back, it resolves again"
