"""TD-588 slice 2 (design §5 *The seams*, [ADR 2026-10-12] *Briefs and flows name no repo's layout*): the
built-in briefs, the five flows' stage texts and `team_skill.md` hold the layout slots, never one repo's
literals — a bare repo's composed briefs name no layout, and this repo's read its own through its
`.shiftlead.yml` and agent-cadence's files."""

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
    "grinder": {
        "{board}",
        "{cadence_rules}",
        "{design_dir}",
        "{gate}",
        "{ledger_check}",
        "{lint}",
        "{merge}",
        "{test}",
    },
    "hunter": {"{board}", "{cadence_rules}", "{design_dir}", "{gate}", "{ledger}", "{merge}", "{test}"},
    "manager": {"{board}", "{cadence_rules}", "{design_dir}", "{gate}", "{merge}", "{test}"},
    "techlead": {"{board}", "{design_dir}", "{gate}", "{ledger}", "{merge}"},
    "auditor": {"{cadence_rules}", "{design_dir}", "{gate}", "{ledger}", "{merge}", "{test}"},
    "sweeper": {"{board}", "{cadence_rules}", "{gate}", "{merge}", "{test}"},
    "fact-checker": set(),
    "designer": {"{board}", "{cadence_rules}", "{merge}"},
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
    # the cadence's slots and `{ledger}` are agent-cadence's paths in any repo (an unserved one composes no
    # brief, TD-1011); outside the slots the text names no layout
    rest = text
    # `{merge}` first: its line holds `{gate}`'s text
    for slot in ("{merge}", "{gate}", "{board}", "{ledger}", "{ledger_check}", "{cadence_rules}"):
        if slot in made["slots"]:
            rest = rest.replace(made["slots"][slot]["text"].replace("{pr}", "<n>"), slot)
    assert not LITERALS.search(rest), LITERALS.search(rest)
    assert not re.search(r"\{(gate|merge|board|ledger|ledger_check|test|lint|design_dir|cadence_rules|pr)\}", text)
    named = {s for s in repoconfig.LAYOUT_SLOTS if s in made["slots"]}
    assert named == NAMED[role]
    if "{gate}" in named:
        assert "python3 scripts/check_cadence.py --pr <n>" in text and made["slots"]["{pr}"] == {"text": "<n>"}


@pytest.mark.parametrize("role", ROLES)
def test_this_repos_brief_reads_its_own_layout(role):
    # this repo pins agent-cadence (dev-cadence TD-129): its cadence slots are the resolver's commands, typed
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
    if "{merge}" in given:
        assert f"{cadence.typed('run', 'forge.py', 'squash-message')} <n> --gate" in text


def test_no_built_in_merges_outside_step_5s_line():
    """TD-1418, design §5 *The seams* (`{merge}`): every built-in brief and flow stage that has a session merge a
    PR names `{merge}`, typed whole as one command, never a bare `gh pr merge`; the bare merge is only the
    fallback sentence inside `{merge}`'s own fill."""
    found = [name for name, text in built_ins() if "gh pr merge" in text]
    assert found == []
    for name, text in built_ins():
        if "{merge}" in text and name != "team_skill.md":
            assert "typed whole as one command" in text, name


# a sentence that has the session merge its own PR on the gate
MERGES = re.compile(r"\bmerges? (?:it )?(?:once the gate passes|on the gate|at the gate)")


def test_a_brief_that_merges_names_step_5s_line():
    """TD-1742: a built-in brief or flow stage that tells its session to merge (*merge once the gate passes*,
    *merges on the gate*) holds `{merge}`, so its rendered brief carries cadence step 5's line; the designer's
    brief once said only *you merge nothing on a held path*, and its design PRs merged with no `Merged-by:`."""
    merging = {name: text for name, text in built_ins() if MERGES.search(text)}
    assert any(name.endswith("designer.md") for name in merging)
    assert [name for name, text in merging.items() if "{merge}" not in text] == []


# design §4.3 *The untrusted-flags guard* (TD-1576): the commands the fact-checker's brief names carry
# no option word off a Gemini tool's safe list and no path-like word, and a text is one single-quoted word
FC_PREFIXES = ("ao ", "git ", "gh ", "head ", "echo ")
FC_SAFE = {"-1", "-n", "--"}
FC_PATHLIKE = ("/", "./", "../", "http://", "https://")
FC_SUFFIXES = (".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd", ".exe")


def test_the_fact_checker_briefs_road_carries_no_word_the_guard_stops_on():
    import shlex

    text = resources.files("shiftlead").joinpath("briefs", "fact-checker.md").read_text(encoding="utf-8")
    spans = [s for s in re.findall(r"`([^`]+)`", text) if s.startswith(FC_PREFIXES)]
    assert any(s.startswith("ao reply ") for s in spans) and any(s.startswith("git show ") for s in spans)
    bad = []
    for span in spans:
        for w in shlex.split(span):
            if (w.startswith("-") and w not in FC_SAFE) or w.startswith(FC_PATHLIKE) or w.endswith(FC_SUFFIXES):
                bad.append((span, w))
        if span.startswith(("ao reply", "ao msg person")) and "'" in span and span.count("'") != 2:
            bad.append((span, "a text is one single-quoted word holding no '"))
    assert bad == []


@pytest.mark.parametrize("role", ("grinder", "designer", "manager"))
def test_an_act_line_is_written_kinded_with_its_doer_named_and_the_persons_marked(tmp_path, role):
    """TD-1625 (design §4.9a *What a session does with a decided line*, §4.5 screen 12 *Three verbs: Have a
    session do it*): a rendered brief writes an `act` line with `--kind act` and `--detail`, names in its
    context who can do the step, marks a step only the person can do — the no-seat line among them — with
    *only you can do this*, and leaves the generic *anything that must outlive this session* command kindless."""
    text, made = repoconfig.resolve_role(repoconfig.load(tmp_path), role).compose()
    board = made["slots"]["{board}"]["text"]
    act = (
        f'board_edit.py add --board {board} --kind act --text "…" --due <date> '
        '--detail \'{"context": "<who can do the step, and why; any suggested command>"}\' --no-commit'
    )
    assert act in text
    no_seat = text.index("*<repo> has no question seat, so no session here can file it*")
    assert text.index("and ending with *only you can do this*", no_seat) < text.index(act)
    assert "this repo's own work, another repo's question seat, or the person" in text
    assert "ends the line's own text with *only you can do this*" in text
    assert "never run by a press" in text
    # the generic board command stays kindless: it is no act line
    for m in re.finditer(re.escape(f"add --board {board} --text "), text):
        assert "--kind" not in text[m.start() : text.index("--no-commit", m.start())]


def test_the_grinder_brief_takes_an_act_line_decided_have_a_session_do_it(tmp_path):
    """TD-1625 (design §4.9a *What a session does with a decided line*): the grinder's decided-line paragraph
    carries the act-line case, its three roads and the closes, and never leaves the line open on a refused send."""
    text, _ = repoconfig.resolve_role(repoconfig.load(tmp_path), "grinder").compose()
    start = text.index("**A decided board line comes first**")
    case = text.index("**An `act` line decided *have a session do it***", start)
    assert case < text.index("`ao progress done board:<key> --pr <n>` ends the claim.", start)
    para = text[case : text.index("ends the claim.", case)]
    for words in (
        "**A step in this repo**",
        "your own work, done in the PR that closes the line",
        "`ao promote`, `ao service`, a team's start or stop",
        "**A step in another repo**",
        "`--why \"handed to <repo>'s question seat: <the ask's id>\"`",
        "*<repo> has no question seat*, *no registered repo <repo>*) makes the step the person's",
        "line is never left open",
        '--owner grinder --kind build --blocked-by "until <tomorrow>"',
        "**A step only the person can do**",
        "`Owner: paul` entry",
        "`--carried-to TD-n`",
        "**A line the gate sweep wrote** (*no-board*, *broken*, *audit*)",
        "Run nothing the detail block suggests",
    ):
        assert words in para, words
