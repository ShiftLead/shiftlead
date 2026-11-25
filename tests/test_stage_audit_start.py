"""A session started for one run of an audit, and what it is told (design §4.9c *Audits start on a clock*, TD-2053)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml

from shiftlead import flow3, stage_audit_start, stage_start, teams

pytestmark = pytest.mark.unit


def wise() -> dict:
    return yaml.safe_load((flow3.PACKAGE_DIR / "design-wise" / flow3.FILE).read_text(encoding="utf-8"))


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(teams, "_person", lambda *_a: ([], False))
    (tmp_path / ".shiftlead.yml").write_text("{}\n")
    org = SimpleNamespace(
        checkout=lambda _repo, _host: str(tmp_path),
        roles={},
        project_of=lambda repo: repo,
        checkouts={"r": str(tmp_path)},
    )
    line = SimpleNamespace(role="auditor", brief="rules.md", profile=None)
    (tmp_path / "rules.md").write_text("THE REPO RULES\n")
    return org, SimpleNamespace(name="core", repo="r", members=[line]), tmp_path


def made(world, name="Docs audit", doc=None, **kw):
    org, team, _ = world
    return stage_audit_start.launch(org, team, doc or wise(), name, host="h", here="h", **kw)


def test_a_run_starts_in_the_auditor_role_on_the_audits_model_its_lane_its_lease(world):
    got = made(world)
    x = got.launch
    assert (x.role, x.lane, x.name, x.team, got.model) == (
        "auditor",
        ["audit:core/docs-audit"],
        "audit-core-docs-audit",
        "core",
        "sonnet",
    )
    assert x.create_params([])["controllers"] == []
    brief = stage_start._body((flow3.STANDARD_DIR / "docs.md").read_text(encoding="utf-8"))
    marks = ["one run of an audit", "## Mechanics", "ao stage end <outcome>", "## This repo's rules", brief]
    at = [x.prompt.index(m) for m in marks]
    assert at == sorted(at)
    assert "THE REPO RULES" in x.prompt and "**audit:core/docs-audit**" in x.prompt
    for slot in ("{lane}", "{flow}", "{stage}"):
        assert slot not in x.prompt


def test_the_outcomes_are_an_audits_and_it_fixes_nothing(world):
    p = made(world, "Tests audit", base="c" * 40).launch.prompt
    for o in ("- `findings-filed`:", "- `nothing-found`:", "- `other`:"):
        assert o in p
    assert "`work-pushed`" not in p and "`ship`" not in p
    assert "fix nothing" in p and "every 6 hours" in p and "c" * 12 in p
    assert "ao msg --kind ask --team core" in p


def test_an_audits_also_is_appended_to_its_brief(world):
    doc = wise()
    doc["audits"][0]["also"] = "Look at the README first."
    assert "Look at the README first." in made(world, doc=doc).launch.prompt


def test_an_audit_the_flow_does_not_have_is_refused(world):
    with pytest.raises(teams.TeamError, match="no audit"):
        made(world, "Code audit")
