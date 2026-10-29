"""TD-588 slice 2 (design §5 *The seams*, [ADR 2026-10-12] *Briefs and flows name no repo's layout*): the
built-in briefs, the five flows' stage texts and `team_skill.md` hold the layout slots, never one repo's
literals — a bare repo's composed briefs name no layout, and this repo's read its own through its
`.shiftlead.yml` and dev-cadence's files."""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

import pytest

from sessionorc import cadence
from shiftlead import repoconfig

pytestmark = pytest.mark.unit

# the ADR's list, and the design's history beside its directory: a repo's layout, outside a slot
LITERALS = re.compile(
    r"docs/cadence\.md|/cadence\b|scripts/|docs/technical_debt\.md|docs/user_attention\.md|docs/design[/-]|pdm run"
)
REPO = Path(__file__).resolve().parents[1]
# the slots each preset's template names: a role that silently loses one fails here
NAMED = {
    "grinder": {"{board}", "{cadence_rules}", "{design_dir}", "{gate}", "{ledger_check}", "{lint}", "{test}"},
    "hunter": {"{board}", "{cadence_rules}", "{design_dir}", "{gate}", "{ledger}", "{test}"},
    "manager": {"{board}", "{cadence_rules}", "{design_dir}", "{gate}", "{test}"},
    "techlead": {"{board}", "{design_dir}", "{gate}", "{ledger}"},
    "auditor": {"{cadence_rules}", "{design_dir}", "{gate}", "{ledger}", "{test}"},
    "sweeper": {"{board}", "{cadence_rules}", "{gate}", "{test}"},
    "fact-checker": set(),
    "designer": {"{board}", "{cadence_rules}"},
}
ROLES = tuple(NAMED)


def built_ins() -> list[tuple[str, str]]:
    pkg = resources.files("shiftlead")
    files = [*pkg.joinpath("briefs").iterdir(), pkg.joinpath("team_skill.md")]
    files += [f for flow in pkg.joinpath("flows").iterdir() if flow.is_dir() for f in flow.iterdir()]
    return [
        (f.name if f.name == "team_skill.md" else str(f), f.read_text(encoding="utf-8"))
        for f in files
        if f.name.endswith(".md")
    ]


def test_the_built_ins_name_no_repos_layout():
    found = [(name, m.group(0)) for name, text in built_ins() for m in LITERALS.finditer(text)]
    assert found == []
    assert (
        len([n for n, _ in built_ins() if "/flows/" in n]) == 5
    )  # td/build, td/design, td/review, build, build-review


@pytest.mark.parametrize("role", ROLES)
def test_a_bare_repos_brief_says_each_seam_in_its_own_words(tmp_path, role):
    text, made = repoconfig.resolve_role(repoconfig.load(tmp_path), role).compose()
    # the cadence's slots and `{ledger}` are dev-cadence's paths in any repo (an unserved one composes no
    # brief, TD-1011); outside the slots the text names no layout
    rest = text
    for slot in ("{gate}", "{board}", "{ledger}", "{ledger_check}", "{cadence_rules}"):
        if slot in made["slots"]:
            rest = rest.replace(made["slots"][slot]["text"].replace("{pr}", "<n>"), slot)
    assert not LITERALS.search(rest), LITERALS.search(rest)
    assert not re.search(r"\{(gate|board|ledger|ledger_check|test|lint|design_dir|cadence_rules|pr)\}", text)
    named = {s for s in repoconfig.LAYOUT_SLOTS if s in made["slots"]}
    assert named == NAMED[role]
    if "{gate}" in named:
        assert "python3 scripts/check_cadence.py --pr <n>" in text and made["slots"]["{pr}"] == {"text": "<n>"}


@pytest.mark.parametrize("role", ROLES)
def test_this_repos_brief_reads_its_own_layout(role):
    # this repo pins dev-cadence (dev-cadence TD-129): its cadence slots are the resolver's commands, typed
    assert cadence.pinned(REPO)
    text, made = repoconfig.resolve_role(repoconfig.load(REPO), role).compose()
    given = {s: made["slots"][s]["text"] for s in repoconfig.LAYOUT_SLOTS if s in made["slots"]}
    assert set(given) == NAMED[role]  # the same slots in this repo as in a bare one
    for slot, words in {
        "{test}": "pdm run test",
        "{lint}": "pdm run lint",
        "{board}": "docs/user_attention.md",
        "{design_dir}": "docs/design/",
        "{cadence_rules}": f"read the file `{cadence.typed('path', 'cadence.md')}` prints, §1–§4",
    }.items():
        if slot in given:
            assert given[slot] == words and words in text, slot
    if "{gate}" in given:
        assert f"{cadence.typed('run', 'check_cadence.py')} --pr <n>" in text
