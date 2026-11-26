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
