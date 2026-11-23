"""The built-in sets (design §4.9d *The built-in seats and their page*, TD-2066): the store, its four writes through
the host agent, and what the page's read says."""

from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace

import pytest

from sessionorc import builtinstore as bs
from sessionorc import hosts
from sessionorc import settings as settings_mod
from sessionorc.agent_common import RpcError
from sessionorc.agent_settings import SettingsMixin
from sessionorc.teamstore import TeamError
from shiftlead import team_show

pytestmark = pytest.mark.unit


def _doc(**more):
    return {"cut_over": "2026-12-01", **more}


def _row(account="acct", models=("opus", "sonnet", "haiku"), state="signed_in", **more):
    return {"account": account, "models": list(models), "state": state, **more}


def test_a_file_with_no_default_reads_the_packages_models_and_an_empty_list():
    got = bs.sets({})
    assert list(got) == ["default"]
    assert got["default"]["models"] == bs.PACKAGE_MODELS and got["default"]["logins"] == []


def test_default_comes_first_then_the_rest_by_name_and_a_seat_left_out_runs_on_the_packages():
    doc = _doc(builtins={"zed": {"logins": []}, "default": {"models": {"sweeper": "opus"}}, "alpha": {}})
    assert list(bs.sets(doc)) == ["default", "alpha", "zed"]
    entry = bs.sets(doc)["default"]
    assert bs.model(entry, "sweeper") == "opus" and bs.model(entry, "tech-lead") == bs.PACKAGE_MODELS["tech-lead"]


def test_a_repo_with_no_pick_or_a_pick_of_no_set_reads_default():
    doc = _doc(
        builtins={"cheap": {}}, repos={"a": {"builtins": "cheap"}, "b": {"pull": True}, "c": {"builtins": "gone"}}
    )
    assert [bs.repo_set(doc, r) for r in ("a", "b", "c", "d")] == ["cheap", "default", "default", "default"]


def test_a_seat_reads_its_repos_set_and_the_first_usable_login_with_no_team_reserve():
    doc = _doc(builtins={"default": {"models": {"sweeper": "haiku"}, "logins": ["c:one", "c:two"]}})
    rows = {"c:one": _row("a", at_reserve=True), "c:two": _row("b")}
    got = bs.seat(doc, "r", "sweeper", rows)
    assert got["set"] == "default" and got["model"] == "haiku" and got["now"]["login"] == "c:two"


def test_every_write_is_refused_before_the_marker():
    doc = {"builtins": {"x": {}}}
    v = bs.version(doc)
    for write in (
        lambda: bs.new(doc, "y"),
        lambda: bs.apply(doc, "default", {"label": "x"}, v),
        lambda: bs.delete(doc, "x", v),
        lambda: bs.pick(doc, "r", "x", v),
    ):
        with pytest.raises(TeamError, match="after the switch-over"):
            write()


def test_a_write_on_a_stale_version_is_refused():
    doc = _doc()
    was = bs.version(doc)
    bs.apply(doc, "default", {"logins": ["c:one"]}, was)
    for write in (
        lambda: bs.apply(doc, "default", {"label": "x"}, was),
        lambda: bs.pick(doc, "r", "default", was),
        lambda: bs.delete(doc, "default", was),
    ):
        with pytest.raises(TeamError, match="reload"):
            write()


def test_a_first_write_on_default_keeps_the_packages_models():
    doc = _doc()
    bs.apply(doc, "default", {"logins": ["c:one"]}, bs.version(doc))
    assert doc["builtins"]["default"]["models"] == bs.PACKAGE_MODELS


def test_a_new_set_takes_defaults_models_and_an_empty_list_and_its_name_is_unique_case_folded():
    doc = _doc(builtins={"default": {"models": {"sweeper": "opus"}, "logins": ["c:one"]}})
    bs.new(doc, "cheap", "Cheap")
    assert doc["builtins"]["cheap"] == {"label": "Cheap", "models": {"sweeper": "opus"}, "logins": []}
    for name in ("CHEAP", "Default", "no spaces", ""):
        with pytest.raises(TeamError):
            bs.new(doc, name)


def test_default_cannot_be_deleted_and_a_named_set_cannot_until_the_pick_moves():
    doc = _doc(builtins={"default": {}, "cheap": {}}, repos={"r": {"builtins": "cheap", "pull": False}})
    with pytest.raises(TeamError, match="always exists"):
        bs.delete(doc, "default", bs.version(doc))
    with pytest.raises(TeamError, match="used by r"):
        bs.delete(doc, "cheap", bs.version(doc))
    bs.pick(doc, "r", "default", bs.version(doc))
    assert doc["repos"]["r"] == {"pull": False}, "default is the key's absence, and the repo's other keys stay"
    bs.delete(doc, "cheap", bs.version(doc))
    assert "cheap" not in doc["builtins"]


def test_a_pick_of_default_on_a_repo_with_nothing_else_leaves_no_repo_row():
    doc = _doc(builtins={"cheap": {}}, repos={"r": {"builtins": "cheap"}})
    bs.pick(doc, "r", "default", bs.version(doc))
    assert "repos" not in doc


@pytest.mark.parametrize(
    "change",
    [
        {},
        {"label": "a", "logins": []},
        {"models": {"manager": "opus"}},
        {"models": {"sweeper": "a b"}},
        {"logins": ["x"]},
    ],
)
def test_a_bad_change_is_refused(change):
    doc = _doc()
    with pytest.raises(TeamError):
        bs.apply(doc, "default", change, bs.version(doc))


def test_an_empty_label_clears_it():
    doc = _doc(builtins={"default": {"label": "Main"}})
    bs.apply(doc, "default", {"label": ""}, bs.version(doc))
    assert "label" not in doc["builtins"]["default"]


def test_cannot_run_names_the_seat_and_the_model_and_a_wait_is_not_it():
    entry = {"models": {"sweeper": "haiku"}, "logins": ["c:one"]}
    rows = {"c:one": _row(models=("opus", "sonnet"))}
    assert bs.cannot_run("default", entry, rows) == [
        "default cannot run the sweeper: no login in its list offers haiku"
    ]
    assert bs.cannot_run("default", entry, {"c:one": _row(state="limited")}) == [], "offered but unusable is a wait"
    empty = bs.cannot_run("x", {"models": {}, "logins": []}, {})
    assert len(empty) == 5 and "its login list is empty" in empty[0]


def test_where_the_org_has_a_director_the_prompts_seat_is_not_read():
    entry = {"models": {}, "logins": ["c:one"]}
    rows = {"c:one": _row(models=("opus", "haiku"))}  # sonnet offered by nothing: prompts, board, unheld
    assert any("prompts" in c for c in bs.cannot_run("d", entry, rows))
    assert not any("prompts" in c for c in bs.cannot_run("d", entry, rows, director=True))


def test_the_pages_read_says_what_each_band_draws():
    doc = _doc(
        builtins={"default": {"logins": ["c:one", "c:far"]}, "cheap": {"models": {"tech-lead": "haiku"}}},
        repos={"s": {"builtins": "cheap"}},
    )
    rows = {"c:one": _row()}
    got = team_show.builtins_view(name="default", doc=doc, rows=rows, roots=["/x/r", "/x/s"], director=True)
    assert got["used_by"] == ["r"] and got["named_by"] == [] and got["repos"][1] == {"repo": "s", "set": "cheap"}
    prompts = next(s for s in got["seats"] if s["key"] == "prompts")
    assert prompts["director"] and prompts["model"] is None
    assert next(s for s in got["seats"] if s["key"] == "sweeper")["now"]["login"] == "c:one"
    assert [lg["state"] for lg in got["logins"]] == ["signed_in", "not_read"], "a node's login is not read here"
    assert [x["name"] for x in got["sets"]] == ["default", "cheap"] and got["sets"][1]["cannot_run"]
    with pytest.raises(ValueError, match="no built-in set"):
        team_show.builtins_view(name="gone", doc=doc, rows=rows, roots=[], director=False)


def test_a_team_page_says_when_its_repos_set_cannot_run_a_seat_and_a_node_team_is_not_checked():
    doc = _doc(
        teams={"a": {"repo": "r", "host": "home", "flow": "f"}, "n": {"repo": "r", "host": "far", "flow": "f"}},
        builtins={"default": {"models": {"sweeper": "haiku"}, "logins": ["c:one"]}},
    )
    rows = {"c:one": _row(models=("opus", "sonnet"))}
    here = team_show.view("a", doc, rows, {}, "home", None, ())
    assert here["builtins"] == "default" and any("sweeper" in c for c in here["builtins_cannot_run"])
    assert team_show.view("n", doc, rows, {}, "home", None, ())["builtins_cannot_run"] == []


class _Agent(SettingsMixin):
    def __init__(self):
        self.saved = 0

    def _graph(self):
        return {}

    async def _team_store_saved(self, before, doc):
        settings_mod.save(doc)
        self.saved += 1


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    settings_mod.save({"cut_over": "2026-12-01"})
    monkeypatch.setattr(hosts, "local_host", lambda: SimpleNamespace(repos=lambda: ["/x/r"], name="home"))
    return _Agent()


def test_the_calls_write_a_set_a_pick_and_a_delete(agent):
    async def go():
        v = bs.version(settings_mod.load())
        got = await agent.rpc_builtins_new(name="cheap", label="Cheap")
        v = got["version"]
        got = await agent.rpc_builtins_set(set="cheap", models={"sweeper": "opus"}, version=v)
        got = await agent.rpc_repo_builtins(repo="r", set="cheap", version=got["version"])
        with pytest.raises(RpcError, match="used by r"):
            await agent.rpc_builtins_delete(set="cheap", version=got["version"])
        with pytest.raises(RpcError, match="not a registered checkout"):
            await agent.rpc_repo_builtins(repo="other", set="cheap", version=got["version"])
        got = await agent.rpc_repo_builtins(repo="r", set="default", version=got["version"])
        await agent.rpc_builtins_delete(set="cheap", version=got["version"])

    asyncio.run(go())
    doc = settings_mod.load()
    assert "cheap" not in doc["builtins"] and agent.saved == 5


def test_a_saved_settings_file_keeps_the_pick_through_a_repos_other_switch(agent):
    doc = settings_mod.load()
    doc["builtins"] = {"cheap": {}}
    bs.pick(doc, "r", "cheap", bs.version(doc))
    settings_mod.save(doc)
    held = copy.deepcopy(settings_mod.load())
    held["repos"] = settings_mod.merge(held.get("repos"), {"r": {"pull": False}})
    settings_mod.save(held)
    assert settings_mod.load()["repos"]["r"] == {"builtins": "cheap", "pull": False}
