"""TD-2068, design §4.9e *The launch on a login*, §4.3 `model_arg`: a launch on a login hands the tool's word for the
seat model's family. Grok Build's is the newest id of the family its home's `models_cache.json` lists, else its
table's; an adapter that declares no `model_arg` (Claude Code, Gemini CLI: the family is the tool's own alias) is
handed the family."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sessionorc import adapters
from sessionorc.agent_common import _model_word
from shiftlead.adapters import grok

pytestmark = pytest.mark.unit


def _cache(home: Path, models: dict) -> Path:
    home.mkdir(exist_ok=True)
    (home / grok.MODELS_CACHE).write_text(json.dumps({"models": models}))
    return home


def test_groks_word_is_the_newest_listed_id_of_the_family(tmp_path):
    home = _cache(
        tmp_path / "g",
        {
            "grok-4.5": {"info": {}},
            "grok-4.10": {"info": {}},
            "grok-4.7": {"info": {}},
            "grok-4.7-build-fast": {"info": {}},
            "grok-5": {"info": {"hidden": True}},
        },
    )
    assert grok.model_arg("grok", home) == "grok-4.10", "newest by version, a hidden one passed over"
    assert grok.model_arg("build-fast", home) == "grok-4.7-build-fast"


def test_groks_word_falls_back_to_its_table_never_the_bare_family(tmp_path):
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / grok.MODELS_CACHE).write_text("not json")
    for home in (None, tmp_path / "missing", tmp_path / "bad", _cache(tmp_path / "other", {"grok-4.7": {}})):
        assert grok.model_arg("build-fast", home) == grok.FAMILY_IDS["build-fast"], home
    assert grok.model_arg("grok", None) == "grok-4.7"
    assert grok.model_arg("no-such-family", None) == "no-such-family", "a family it does not know is handed back"


def test_an_adapter_without_model_arg_is_handed_the_family():
    for name in ("claude-code", "gemini"):
        ad = adapters.get(name)
        assert "model_arg" not in adapters.implements(ad), f"{name}'s family is its own alias"
        assert _model_word(ad, "flash") == "flash"


def test_the_core_reads_model_arg_against_the_logins_folder(tmp_path):
    home = _cache(tmp_path / "g", {"grok-4.9": {"info": {}}})
    ad = adapters.get("grok")
    assert _model_word(ad, "grok", str(home)) == "grok-4.9"
    assert _model_word(ad, "grok", "") == "grok-4.7", "no folder: the table's id"


def test_a_failing_model_arg_hands_the_family_on():
    class Broken:
        implements = frozenset({"model_arg"})

        def model_arg(self, family, home=None):
            raise TypeError("boom")

    assert _model_word(Broken(), "opus") == "opus"


async def test_a_create_on_a_login_hands_the_tools_word_for_the_family(agent, tmp_path, hookstub, monkeypatch):
    """The create reads `model_arg` against the login's folder, so the launch is handed the id, not the family."""
    from sessionorc import paths
    from sessionorc.adapters import LaunchSpec
    from sessionorc.client import LocalClient

    (paths.home() / "logins.yml").write_text(
        f"logins:\n  hookstub:grind: {{folder: {tmp_path / 'g'}, account: acct-1}}\naccounts: {{}}\nforgotten: {{}}\n"
    )
    seen: list = []

    def launch(*, profile, resume, prompt, unattended, cwd, name="", **kw):
        seen.append(kw.get("model"))
        return LaunchSpec(argv=["bash", "--norc"])

    monkeypatch.setattr(hookstub, "launch", launch)
    monkeypatch.setattr(hookstub, "implements", frozenset({*adapters.implements(hookstub), "model_arg"}), raising=False)
    monkeypatch.setattr(hookstub, "model_arg", lambda family, home=None: f"{family}@{home.name}", raising=False)
    (tmp_path / "w").mkdir()
    async with LocalClient() as person:
        await person.call(
            "create", name="w", dir=str(tmp_path / "w"), adapter="hookstub", login="grind", seat_model="opus"
        )
    assert seen == ["opus@g"]


def test_the_logins_folder_written_with_a_tilde_is_expanded(tmp_path, monkeypatch):
    """TD-2267: a login's folder may be written `~/…` in `logins.yml`; the core reads `model_arg` against the folder it
    names, so the cache there decides the word rather than the table's id."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _cache(tmp_path / "g", {"grok-4.9": {"info": {}}})
    assert _model_word(adapters.get("grok"), "grok", "~/g") == "grok-4.9"


class _Mapper:
    """An adapter whose `model_arg` answers `word`, declared in `implements` or not."""

    def __init__(self, word, declared: bool):
        self.word = word
        self.implements = ("model_arg",) if declared else ()

    def model_arg(self, family, home=None):
        return self.word


@pytest.mark.parametrize(
    ("word", "declared"), [("its-own-id", False), (None, True), ("", True)], ids=["undeclared", "none", "empty"]
)
def test_an_undeclared_or_empty_model_arg_hands_the_family(word, declared):
    """TD-2267, §4.3 *The conformance suite*: a `model_arg` the adapter does not declare is never called, and a
    declared one that answers no word hands the family on rather than nothing."""
    assert _model_word(_Mapper(word, declared), "opus") == "opus"


@pytest.mark.parametrize(
    "text",
    [
        json.dumps(["grok-4.9"]),
        json.dumps({"models": ["grok-4.9"]}),
        json.dumps({"models": {"grok-4.9": None, "grok-4.5": {"info": {}}}}),
    ],
    ids=["file-a-list", "models-a-list", "entry-not-a-table"],
)
def test_groks_word_from_an_odd_cache_is_an_id_never_the_bare_family(tmp_path, text):
    """TD-2267, §4.3: Grok Build refuses the bare family, so a cache file of an unexpected shape still gives an id —
    the table's, or the newest one listed where its entry is not a table — and never raises into the fallback."""
    (tmp_path / "g").mkdir()
    (tmp_path / "g" / grok.MODELS_CACHE).write_text(text)
    want = "grok-4.9" if "grok-4.5" in text else grok.FAMILY_IDS["grok"]
    assert grok.model_arg("grok", tmp_path / "g") == want
    assert _model_word(adapters.get("grok"), "grok", str(tmp_path / "g")) == want != "grok"
