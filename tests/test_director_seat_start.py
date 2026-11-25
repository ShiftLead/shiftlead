"""TD-642 slice 4, design §4.9b *The director seat*: any Start or Apply writes the org's director seat where
`org.yml` defines `director:` and no record holds it — held for rule 3, trigger `prompt`, holding `permit`, in a
directory of its own, no team and no project — its brief `director.md` with `{org}` the Org block, read from the
repo registry at each fill and never from `projects:`; a director on a profile that asks is refused and said."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from conftest import park_ticks

from sessionorc import brief
from sessionorc.client import LocalClient
from shiftlead import org as orgmod
from shiftlead import teamrun, teams

HOST = "kmaster"


def _org(tmp_path: Path, monkeypatch, director=None, *, title="Shift") -> orgmod.Org:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
    monkeypatch.setattr(teams, "DIRECTOR_DIR", str(tmp_path / "director"))
    (home / "profiles.yml").write_text(
        "profiles:\n  grind: {adapter: claude-code}\n  asks: {adapter: claude-code, permission_prompts: ask}\n"
        "  close: {adapter: claude-code, permission_prompts: all}\n"
    )
    (tmp_path / "alpha" / ".git").mkdir(parents=True, exist_ok=True)
    doc: dict = {
        "projects": {"p": {"title": title, "repos": {"alpha": {HOST: str(tmp_path / "alpha")}}}},
        "teams": {"t": {"repo": "alpha", "members": [{"role": "grinder", "name": "g"}]}},
    }
    if director is not None:
        doc["director"] = director
    (home / "org.yml").write_text(yaml.safe_dump(doc))
    return orgmod.load()


def _fake(records=()):
    calls: list[tuple[str, dict]] = []

    def call(method, **params):
        calls.append((method, params))
        if method == "name_check":
            return {"name": params["name"], "verdict": "free"}
        if method == "list":
            return list(records)
        if method == "create":
            return {"id": f"ao-{params['name']}", "name": params["name"]}
        if method in ("sweep_switch", "witness_press"):
            return {}
        raise AssertionError(method)

    return call, calls


@pytest.mark.unit
def test_the_org_block_is_every_registered_checkout_named_with_its_heading():
    got = brief.org_block({"alpha": "Shift"}, ["/src/alpha", "/src/beta"])
    assert got.splitlines() == [brief.ORG_HEAD, "", "- alpha: /src/alpha (project Shift)", "- beta: /src/beta"]
    assert brief.org_block(None, []).endswith(brief.ORG_NONE)


@pytest.mark.unit
def test_the_fill_reads_the_registry_as_it_stands(tmp_path, monkeypatch):
    """§4.9b: built from the repo registry at each fill, so a repo registered since the start is in the next."""
    base = tmp_path / "director.md"
    base.write_text("brief\n\n{org}\n")
    made = {"base": str(base), "slots": {"{org}": {"checkouts": {"headings": {"alpha": "Shift"}}}}}
    roots = ["/src/alpha"]
    monkeypatch.setattr(brief, "org_block", lambda h, r=None, _f=brief.org_block: _f(h, list(roots)))
    first, sources = brief.fill(made, merged=False)
    roots.append("/src/beta")
    second, _ = brief.fill(made, merged=False)
    assert "- alpha: /src/alpha (project Shift)" in first and "beta" not in first
    assert "- beta: /src/beta" in second and [s["path"] for s in sources] == [str(base)]


@pytest.mark.unit
def test_no_director_defined_writes_none(tmp_path, monkeypatch):
    org = _org(tmp_path, monkeypatch)
    assert teams.director_create(org) is None
    call, calls = _fake()
    assert teamrun.write_director(call, org) == [] and calls == []


@pytest.mark.unit
def test_the_director_is_a_held_seat_of_no_team_holding_permit(tmp_path, monkeypatch):
    org = _org(tmp_path, monkeypatch, {"profile": "grind"})
    p = teams.director_create(org)
    assert p is not None
    assert (p["name"], p["role"], p["profile"], p["adapter"]) == ("director", "director", "grind", "claude-code")
    assert p["seat"] == {"trigger": "prompt"} and p["capabilities"] == ["permit"] and p["controllers"] == []
    assert p["held"] and p["unattended"] and p["supervised"] and p["lane"] == []
    assert "team" not in p and "project" not in p and "repo" not in p and "worktree" not in p
    assert p["dir"] == str(tmp_path / "director")
    assert p["prompt_from"]["base"].endswith("briefs/director.md")
    assert p["prompt_from"]["slots"] == {"{org}": {"checkouts": {"headings": {"alpha": "Shift"}}}}
    assert "{org}" not in p["prompt"] and brief.ORG_HEAD in p["prompt"]


@pytest.mark.unit
def test_a_brief_the_org_names_is_read_beside_the_org_file(tmp_path, monkeypatch):
    org = _org(tmp_path, monkeypatch, {"brief": "mine.md"})
    (tmp_path / "home" / "mine.md").write_text("my director\n{org}\n")
    p = teams.director_create(org)
    assert p is not None and p["prompt"].startswith("my director\n" + brief.ORG_HEAD)
    assert p["prompt_from"]["base"] == str(tmp_path / "home" / "mine.md")


@pytest.mark.unit
@pytest.mark.unit
def test_a_director_naming_no_profile_launches_on_the_one_its_role_gives(tmp_path, monkeypatch):
    """§4.9e *The answers file*: the role's precedence where `director:` names none, `director:`'s own above it."""
    org = _org(tmp_path, monkeypatch, {})
    assert teams.director_create(org)["profile"] == "", "neither says: the profiles file's default"
    org.roles = {"director": {"profile": "grind"}}
    assert org.director_profile() == "grind" and teams.director_create(org)["profile"] == "grind"
    org.roles = {"director": {"profile": "asks"}}
    with pytest.raises(teams.TeamError, match="permission_prompts: ask"):
        teams.director_create(org)
    org.director.profile = "grind"
    assert teams.director_create(org)["profile"] == "grind", "director:'s own wins over its role's"


@pytest.mark.parametrize("profile", ["asks", "close"])
def test_a_director_on_a_profile_that_asks_is_refused_and_said(tmp_path, monkeypatch, profile):
    """§4.9b *Its first read*: nothing above the director would answer its own prompts."""
    org = _org(tmp_path, monkeypatch, {"profile": profile})
    with pytest.raises(teams.TeamError, match=r"permission_prompts: (ask|all)"):
        teams.director_create(org)
    call, calls = _fake()
    said = teamrun.write_director(call, org)
    assert len(said) == 1 and "not written" in said[0] and "permission_prompts" in said[0]
    assert not any(m == "create" for m, _ in calls)


@pytest.mark.unit
def test_a_start_writes_the_director_once_and_says_so(tmp_path, monkeypatch):
    org = _org(tmp_path, monkeypatch, {})
    call, calls = _fake()
    _plan, result = teamrun.start(call, org, "t", HOST)
    made = [p for m, p in calls if m == "create" and p["name"] == "director"]
    assert len(made) == 1 and made[0]["held"] and (tmp_path / "director").is_dir()
    assert f"director: {teamrun.DIRECTOR_LINE}" in result["notes"]
    # a record of its trigger holds it — held, filled or ended — so the next start writes none
    for state in ("closed", "idle", "exited"):
        rec = {"id": "ao-director", "name": "director", "state": state, "seat": {"trigger": "prompt"}}
        call, calls = _fake([rec])
        assert teamrun.write_director(call, org) == []
        assert not any(m == "create" for m, _ in calls)
    # one superseded holds nothing
    rec = {"id": "ao-director", "state": "closed", "seat": {"trigger": "prompt"}, "superseded_by": "x"}
    call, calls = _fake([rec])
    assert teamrun.write_director(call, org) == [f"director: {teamrun.DIRECTOR_LINE}"]


@pytest.mark.unit
def test_an_apply_writes_the_director_on_a_stopped_team(tmp_path, monkeypatch):
    org = _org(tmp_path, monkeypatch, {})
    call, calls = _fake()
    out = teamrun.apply(call, org, "t", HOST)
    assert out["notes"] == [f"director: {teamrun.DIRECTOR_LINE}"]
    assert [p["name"] for m, p in calls if m == "create"] == ["director"]


@pytest.mark.unit
def test_a_refused_create_is_said_and_the_start_stands(tmp_path, monkeypatch):
    org = _org(tmp_path, monkeypatch, {})
    call, _ = _fake()

    def refusing(method, **params):
        if method == "create" and params["name"] == "director":
            raise RuntimeError("needs the permit grant")
        return call(method, **params)

    _plan, result = teamrun.start(refusing, org, "t", HOST)
    assert any(n.startswith("director: the org's director seat not written — needs") for n in result["notes"])


@pytest.mark.integration
async def test_the_home_writes_the_director_held(agent, tmp_path, monkeypatch):
    """The create a Start hands is one the home takes from the person: a held seat with `permit`, in a
    directory of no repo, closed with no pane until rule 3 fills it."""
    await park_ticks(agent)
    org = _org(tmp_path, monkeypatch, {})
    p = teams.director_create(org)
    assert p is not None
    Path(p["dir"]).mkdir(parents=True)
    async with LocalClient() as person:
        rec = await person.call("create", **p)
    s = agent.sessions[rec["id"]]
    assert s.state == "closed" and s.seat == {"trigger": "prompt"} and "permit" in s.capabilities
    assert s.unattended and s.supervised and not s.team and not s.project and s.dir == p["dir"]


@pytest.mark.unit
def test_a_sessions_start_writes_no_director_and_says_so(tmp_path, monkeypatch):
    """§4.8: the seat holds `permit`, which no session grants, so a session's own Start or Apply writes none."""
    org = _org(tmp_path, monkeypatch, {})
    call, calls = _fake()
    assert teamrun.write_director(call, org, "ao-alpha-lead") == [f"director: {teamrun.DIRECTOR_BY_PERSON}"]
    assert not any(m == "create" for m, _ in calls)


@pytest.mark.unit
def test_a_default_profile_that_asks_is_refused_too(tmp_path, monkeypatch):
    org = _org(tmp_path, monkeypatch, {})
    (tmp_path / "home" / "profiles.yml").write_text(
        "default: asks\nprofiles:\n  asks: {adapter: claude-code, permission_prompts: ask}\n"
    )
    with pytest.raises(teams.TeamError, match=r"permission_prompts: ask"):
        teams.director_create(org)
