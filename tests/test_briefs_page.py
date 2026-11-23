"""The Briefs page and its store (design §4.9c *Where a brief lives*, §4.5a *Briefs page*, TD-2055)."""

from __future__ import annotations

import pytest

from sessionorc import briefs, mail
from shiftlead import flow3
from shiftlead.ui import app as app_mod

pytestmark = pytest.mark.unit


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    return tmp_path


def flow(home, name, brief, own=False):
    d = home / "flows" / name
    d.mkdir(parents=True)
    (d / "flow.yml").write_text(f"format: 3\nname: {name}\nstages:\n- name: Build\n  does: build\n  brief: {brief}\n")
    if own:
        (d / "briefs").mkdir()
        (d / "briefs" / f"{brief}.md").write_text("---\nkind: build\n---\nmine\n")


def test_a_saved_brief_is_offered_to_its_kind_only(home):
    briefs.save("careful", "build", "Go slowly.")
    assert [b["name"] for b in flow3.offered("build")] == ["build", "careful"]
    assert [b["name"] for b in flow3.offered("review")] == ["review"]
    assert [b["name"] for b in flow3.offered("audit")] == ["docs", "tests", "code"]
    assert flow3.brief_kind((home / "briefs" / "careful.md").read_text()) == "build"


def test_deleting_a_brief_a_flow_names_is_refused_naming_the_flow(home):
    got = briefs.save("careful", "build", "Go slowly.")
    flow(home, "mine", "careful")
    with pytest.raises(briefs.BriefError, match="mine"):
        briefs.delete("careful", got["version"])
    assert (home / "briefs" / "careful.md").exists()


def test_a_flows_own_brief_of_that_name_does_not_hold_the_orgs(home):
    got = briefs.save("careful", "build", "Go slowly.")
    flow(home, "mine", "careful", own=True)
    assert briefs.delete("careful", got["version"]) == {"name": "careful", "deleted": True}


def test_an_unreadable_flow_holds_the_delete(home):
    got = briefs.save("careful", "build", "Go slowly.")
    (home / "flows" / "broken").mkdir(parents=True)
    (home / "flows" / "broken" / "flow.yml").write_text("stages: [")
    with pytest.raises(briefs.BriefError, match=r"broken \(unreadable\)"):
        briefs.delete("careful", got["version"])


def test_a_brief_a_flow_names_keeps_its_kind(home):
    got = briefs.save("careful", "build", "Go slowly.")
    flow(home, "mine", "careful")
    with pytest.raises(briefs.BriefError, match="keeps its kind"):
        briefs.save("careful", "review", "Go slowly.", got["version"])


@pytest.mark.parametrize("name", ["build", "../evil", "", ".hidden", "a/b"])
def test_a_name_that_is_standard_or_leaves_the_directory_is_refused(home, name):
    with pytest.raises(briefs.BriefError):
        briefs.save(name, "build", "text")
    assert not list(home.rglob("evil*"))


def test_a_stale_save_and_a_duplicate_new_are_refused(home):
    got = briefs.save("careful", "build", "one")
    with pytest.raises(briefs.BriefError, match="already exists"):
        briefs.save("careful", "build", "two")
    briefs.save("careful", "build", "two", got["version"])
    with pytest.raises(briefs.BriefError, match="reload"):
        briefs.save("careful", "build", "three", got["version"])


@pytest.mark.parametrize("text", ["---\nfirst line is a rule", "before\n---\nafter", "kind: review"])
def test_a_briefs_text_survives_a_save_and_a_read(home, text):
    got = briefs.save("careful", "build", text)
    assert got["text"].strip() == text
    again = briefs.save("careful", "build", got["text"], got["version"])
    assert again["version"] == got["version"] and briefs.own()[0]["kind"] == "build"


def test_a_delete_that_lost_the_race_is_stale(home, monkeypatch):
    got = briefs.save("careful", "build", "text")
    monkeypatch.setattr(briefs.Path, "unlink", lambda self: (_ for _ in ()).throw(FileNotFoundError()))
    with pytest.raises(briefs.BriefError, match="reload"):
        briefs.delete("careful", got["version"])


def test_a_brief_save_is_a_persons_own_act():
    assert "brief_save" in mail.PERSON_ONLY


def test_the_page_draws_standard_read_only_and_own_with_controls(home, monkeypatch):
    from fastapi.testclient import TestClient

    own = [{"name": "careful", "kind": "build", "text": "Go <slowly>.", "version": "v1"}]

    async def call(method, **params):
        return {"briefs": own} if method == "briefs" else {}

    monkeypatch.setattr(app_mod, "agent_call", call)
    with TestClient(app_mod.create_app()) as c:
        text = c.get("/briefs").text
    assert 'data-brief="careful"' in text and "Go &lt;slowly&gt;." in text and "data-brief-delete" in text
    for name in flow3.STANDARD:
        assert f'data-standard="{name}"' in text
    standard = text[text.index("Standard briefs") :]
    assert "<textarea" not in standard and "data-brief-delete" not in standard
    assert '<a href="/briefs" class="on"' in text
    assert text.count("choose a kind") == 1  # the blank form's; a brief with a kind keeps its own


def test_a_brief_with_no_kind_is_never_saved_as_the_first_kind(home, monkeypatch):
    from fastapi.testclient import TestClient

    async def call(method, **params):
        return {"briefs": [{"name": "old", "kind": None, "text": "t", "version": "v"}]} if method == "briefs" else {}

    monkeypatch.setattr(app_mod, "agent_call", call)
    with TestClient(app_mod.create_app()) as c:
        text = c.get("/briefs").text
    form = text[text.index('data-brief="old"') :]
    assert '<option value="" disabled selected>choose a kind</option>' in form
