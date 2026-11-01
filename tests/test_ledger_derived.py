"""TD-228 slice 1, design §4.4 *Repo facts*: pickable is derived from `**Blocked by:**`, never
written, by cadence §2.4's rule — the rule agent-cadence's `scripts/ledger.py` applies — so the home
and the repo's own tool give one answer. These tests hold the two readers equal."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import pinned_script, repo_ledger

from sessionorc import ledger

ROOT = Path(__file__).parents[1]


def _script(cwd: Path, reg_dir: Path, *args: str) -> dict:
    """The synced script's `--list --json`, its roster pointed at `reg_dir` alone."""
    env = {**os.environ, "AGENT_CADENCE_REG_DIR": str(reg_dir)}
    cp = subprocess.run(
        [sys.executable, str(pinned_script("ledger.py")), "--list", "--json", *args],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=60, check=True,
    )  # fmt: skip
    return json.loads(cp.stdout)


def _home(text: str, archive: str | None, roots: list[str]) -> dict[str, dict]:
    return {e["id"]: e for e in ledger.entries(text, archive, ledger.Registry(roots))}


def _same(script: dict, home: dict[str, dict]) -> None:
    got = {e["id"]: e for e in script["entries"]}
    assert set(got) == set(home)
    for tid, s in got.items():
        h = home[tid]
        assert (h["pickable"] == "yes", h["type"], h["blocked_by"]) == (s["pickable"], s["type"], s["blocked_by"]), tid


def test_the_home_derives_what_the_script_derives_on_this_ledger(tmp_path):
    """The equality test: the whole record, not only the ids. Neither reader
    has a roster, so a `<repo>#TD-NNN` item keeps its block in both."""
    home = _home(*repo_ledger(), [])
    _same(_script(ROOT, tmp_path / "no-roster"), home)
    assert any(e["pickable"] == "yes" for e in home.values()) and any(e["pickable"] == "no" for e in home.values())


LEDGER = """# Technical Debt

<!--
## TD-001: the template
**Blocked by:** TD-999
-->

## TD-010: nothing blocks it

**Priority:** High
**Status:** Open

## TD-011: blocked by an open entry

**Priority:** Medium
**Type:** feature
**Blocked by:** TD-010

## TD-012: blocked by an archived one

**Priority:** Medium
**Blocked by:** TD-005

## TD-013: blocked by an id in neither file

**Priority:** Low
**Blocked by:** TD-777

## TD-014: waits on the person

**Priority:** Medium
**Blocked by:** decision (Paul) — docs/user_attention.md, the 2026-09-28 item, TD-010

## TD-015: an unreadable item, and one after the decision's comma

**Priority:** Medium
**Blocked by:** TD-005, soon, decision (Paul), TD-010

## TD-016: an empty line blocks nothing

**Priority:** Low
**Type:** chore
**Blocked by:**

## TD-017: another repo's entries

**Priority:** Medium
**Blocked by:** other#TD-002, other#TD-003

## TD-018: another repo's open entry, and one not on the registry

**Priority:** Medium
**Blocked by:** other#TD-003, nowhere#TD-001

## TD-2: a short id, and a Type the script reads as debt

**Type:** feature,

## TD-019: a blocker below the header, spelt as the script does not read it

**Priority:** Low

**Blocked-by:** TD-010
**Type:** `feature`
"""

ARCHIVE = """# Archive

## TD-005: done long ago

**Resolved:** 2026-09-01
"""


def _repo(path: Path, ledger_text: str, archive: str | None) -> Path:
    (path / "docs").mkdir(parents=True)
    (path / "docs" / "technical_debt.md").write_text(ledger_text, encoding="utf-8")
    if archive is not None:
        (path / "docs" / "technical_debt_archive.md").write_text(archive, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def test_the_rule_and_another_repos_entries_through_one_registry(tmp_path):
    """Two scratch repos and one scratch registry that both readers are pointed at: `other`'s
    TD-002 is archived there, its TD-003 open; `nowhere` is not listed."""
    here = _repo(tmp_path / "here", LEDGER, ARCHIVE)
    other = _repo(
        tmp_path / "other",
        "# Technical Debt\n\n## TD-003: open there\n\n**Priority:** Low\n",
        "# Archive\n\n## TD-002: archived there\n",
    )
    reg = tmp_path / "reg"
    reg.mkdir()
    (reg / "repos.txt").write_text(f"{here}\n{other}\n", encoding="utf-8")
    home = _home(LEDGER, ARCHIVE, [str(here), str(other)])
    _same(_script(here, reg), home)
    assert {t for t, e in home.items() if e["pickable"] == "yes"} == {"TD-010", "TD-012", "TD-016", "TD-2", "TD-019"}
    assert home["TD-2"]["type"] == home["TD-019"]["type"] == "debt", "the Type's first word, as the script splits it"
    assert home["TD-011"]["blocked_by"] == ["TD-010"] and home["TD-013"]["blocked_by"] == ["TD-777"]
    assert home["TD-014"]["blocked_by"] == ["decision (Paul)"], "what follows the decision is its pointer"
    assert home["TD-015"]["blocked_by"] == ["decision (Paul)", "'after the decision: TD-010'", "'soon'"]
    assert home["TD-017"]["blocked_by"] == ["other#TD-003"], "archived there lifts it; open there blocks"
    assert home["TD-018"]["blocked_by"] == ["other#TD-003", "nowhere#TD-001"]
    assert (home["TD-011"]["type"], home["TD-016"]["type"]) == ("feature", "debt"), "an unknown Type reads as debt"
    assert home["TD-014"]["for_page"] == "for-you", "blocked by a decision is the person's"


def test_a_name_two_checkouts_share_keeps_the_block(tmp_path):
    a = _repo(tmp_path / "a" / "other", "# L\n", "# A\n\n## TD-002: archived\n")
    b = _repo(tmp_path / "b" / "other", "# L\n", "# A\n\n## TD-002: archived\n")
    assert ledger.Registry([str(a)])("other#TD-002") == ("archived", "")
    state, why = ledger.Registry([str(a), str(b)])("other#TD-002")
    assert (state, "registry" in why) == ("unresolved", True), why
    state, why = ledger.Registry([str(a)])("other#TD-009")
    assert (state, "neither" in why) == ("unresolved", True), "an id in neither file, and it says so"


def test_an_id_headed_twice_is_blocked_by_what_blocks_either():
    """TD-585 slice 6: ledgerboard keys its reading by id, so a repeated heading takes both sections'
    blockers — the safe direction — never the last section's alone."""
    text = "## TD-005: a\n\n**Blocked by:** TD-009\n\n## TD-005: b\n\n**Priority:** Low\n\n## TD-009: open\n"
    got = ledger.entries(text)
    assert [(e["id"], e["blocked_by"], e["pickable"]) for e in got[:2]] == [("TD-005", ["TD-009"], "no")] * 2


def test_a_written_pickable_line_is_not_read():
    """TD-228 slice 4: the fallback is gone, so a ledger that still writes the line is read as if
    it did not — in the header block or below it."""
    text = "## TD-020: marked\n\n**Priority:** Low\n**Pickable:** no — the live look is left\n"
    assert ledger.entries(text)[0]["pickable"] == "yes"
    below = "## TD-022: marked below\n\n**Priority:** Low\n\n**Pickable:** no\n"
    assert ledger.entries(below)[0]["pickable"] == "yes"
    yes = "## TD-021: blocked\n\n**Blocked by:** TD-020\n**Pickable:** yes\n\n## TD-020: open\n"
    assert ledger.entries(yes)[0]["pickable"] == "no", "a written yes adds nothing"


def test_a_ledger_with_no_header_lines_gives_free_pick_every_unblocked_entry():
    got = ledger.entries(LEDGER, ARCHIVE)
    matched = {e["id"] for e in got if ledger.lane_matches(["free-pick"], e)}
    assert matched == {e["id"] for e in got if not e["blocked_by"]} == {"TD-010", "TD-012", "TD-016", "TD-2", "TD-019"}
    assert not any(ledger.lane_matches(["design-first"], e) for e in got)


@pytest.mark.parametrize(
    ("kind", "owner", "lane", "matches"),
    [
        ("", "", ["free-pick"], True),
        ("build", "grinder", ["free-pick", "owner:grinder"], True),
        ("live-check", "", ["free-pick"], False),
        ("evaluation", "", ["free-pick"], False),
        ("design-first", "designer", ["design-first", "owner:designer"], True),
        ("design-first", "", ["free-pick"], False),
        ("build", "anchor", ["free-pick", "owner:grinder"], False),
    ],
)
def test_lane_words_read_the_derived_field_with_build_for_no_kind(kind, owner, lane, matches):
    head = "".join(f"**{k}:** {v}\n" for k, v in (("Kind", kind), ("Owner", owner)) if v)
    e = ledger.entries(f"## TD-030: x\n\n{head}")[0]
    assert ledger.lane_matches(lane, e) is matches


def test_the_page_kinds_in_order():
    """§4.4 *Repo facts*' seven kinds (TD-418, built by TD-428 slice 6), each entry in the first that
    takes it: for you → blocked → design → live check → pickable → evaluation → other."""

    def kind(block: str, live=None) -> str:
        return ledger.entries(f"## TD-040: x\n\n{block}\n\n## TD-041: open\n", live=live)[0]["for_page"]

    assert kind("**Owner:** paul") == "for-you"
    assert kind("**Kind:** design-first\n**Blocked by:** decision (Paul)") == "for-you"
    assert kind("**Kind:** build\n**Blocked by:** TD-041, decision (paul)") == "for-you"  # the person's first
    # *blocked*: any item other than a decision, whatever the Kind and whatever decision stands beside it
    for block in (
        "**Kind:** build\n**Blocked by:** TD-041",
        "**Kind:** build\n**Blocked by:** TD-041, decision (anchor)",
        "**Kind:** design-first\n**Blocked by:** TD-041",
        "**Kind:** build\n**Blocked by:** TD-041, decision (designer)",
        "**Kind:** live-check #12\n**Blocked by:** TD-041",
        "**Owner:** anchor\n**Kind:** decision\n**Blocked by:** TD-041",  # TD-077's shape
        "**Owner:** anchor\n**Kind:** live-check #343\n**Blocked by:** TD-041",  # TD-052's shape
        "**Kind:** build\n**Blocked by:** other#TD-002",  # a cross-repo blocker no registry resolves
        "**Kind:** build\n**Blocked by:** soon",  # an item the reader cannot read
    ):
        assert kind(block) == "blocked", block
    assert kind("**Kind:** design-first") == "design"
    # a decision owed to the designer is `Kind: design-first`, never a `decision (designer)` item (TD-1296)
    assert kind("**Kind:** build\n**Blocked by:** decision (designer)") == "other"
    assert kind("**Kind:** design-first\n**Blocked by:** decision (anchor)") == "design"
    assert kind("**Kind:** live-check #12") == "live-check"
    assert kind("**Kind:** live-check #12", live=lambda n: True) == "live-check"  # live or not
    assert kind("**Kind:** live-check #12\n**Blocked by:** decision (anchor)") == "live-check"
    assert kind("**Kind:** build") == "pickable" and kind("") == "pickable"
    assert kind("**Kind:** evaluation") == "evaluation"
    # the residue, flagged: a decision owed to anyone but the person, and a `Kind:
    # decision` not the person's (§4.9b *No anchor seat*, TD-757)
    assert kind("**Kind:** build\n**Blocked by:** decision (anchor)") == "other"
    assert kind("**Owner:** anchor\n**Kind:** decision") == "other"
    assert kind("**Kind:** build\n**Blocked by:** decision (techlead)") == "other"
    assert kind("**Owner:** grinder\n**Kind:** decision") == "other"
    got = ledger.entries("## TD-040: x\n\n**Blocked by:** decision (techlead)\n\n## TD-042: y\n")
    assert ledger.flags(got) == ["TD-040: fits no page kind — check its Owner, Kind and Blocked by"]
    got = ledger.entries("## TD-043: z\n\n**Kind:** evaluation\n")
    assert ledger.flags(got) == [
        "TD-043: no lane takes an evaluation — write it as a build whose Fix is the write-up, or as design-first"
    ]
    assert ledger.KINDS == ("for-you", "blocked", "design", "live-check", "pickable", "evaluation", "other")


def test_for_you_is_what_waits_on_the_person_and_a_designer_decision_is_no_case_of_its_own():
    """TD-367/TD-368, design §4.4 *Repo facts* and §6 rule 6: *for you* is `Owner: paul` or a
    `decision (paul)`, any case; a decision owed to the designer is `Kind: design-first`, so a build on
    `decision (designer)` is *other* like any decision not the person's (TD-1296); a `Kind: decision`
    that is not the person's and a build on `decision (anchor)` are *other* since the anchor seat is
    retired (TD-757), and in no grinder or designer lane."""
    text = (
        "## TD-050: the person's\n\n**Owner:** paul\n**Kind:** evaluation\n\n"
        "## TD-051: on the person's decision\n\n**Owner:** grinder\n**Kind:** build\n"
        "**Blocked by:** decision (Paul)\n\n"
        "## TD-052: on the designer's\n\n**Owner:** grinder\n**Kind:** build\n**Blocked by:** decision (designer)\n\n"
        "## TD-053: the anchor's decision\n\n**Owner:** anchor\n**Kind:** decision\n\n"
        "## TD-054: on the anchor's\n\n**Owner:** grinder\n**Kind:** build\n**Blocked by:** decision (anchor)\n"
    )
    got = {e["id"]: e for e in ledger.entries(text)}
    assert {i: e["for_page"] for i, e in got.items()} == {
        "TD-050": "for-you",
        "TD-051": "for-you",
        "TD-052": "other",
        "TD-053": "other",
        "TD-054": "other",
    }
    designer, grinder = ["design-first", "owner:designer"], ["free-pick", "owner:grinder"]
    assert [i for i, e in got.items() if ledger.lane_matches(designer, e)] == []
    assert [i for i, e in got.items() if ledger.lane_matches(grinder, e)] == []
    assert got["TD-052"]["pickable"] == "no"


def test_the_archive_is_read_beside_the_ledger(tmp_path):
    from datetime import UTC, datetime

    _repo(tmp_path / "r", LEDGER, ARCHIVE)
    got = {e["id"]: e for e in ledger.reading(tmp_path / "r", datetime.now(UTC), with_history=False)["entries"]}
    assert got["TD-012"]["pickable"] == "yes", "its blocker is archived beside it"
    assert ledger.archive_path("docs/technical_debt.md") == "docs/technical_debt_archive.md"
    assert ledger.archive_path("notes/ledger.md") == "notes/ledger_archive.md"


def test_a_pass_that_rereads_one_repo_still_resolves_among_the_whole_registry(tmp_path):
    """The techlead's read of #793: a pass re-reads only the checkouts whose ledger moved, and a
    `<repo>#TD-NNN` blocker is still looked up among every checkout the registry lists."""
    from sessionorc.agent_tick import TickMixin

    here = _repo(tmp_path / "here", "# L\n\n## TD-010: x\n\n**Blocked by:** other#TD-002\n", None)
    other = _repo(tmp_path / "other", "# L\n", "# A\n\n## TD-002: archived there\n")
    roots = [str(here), str(other)]
    got = TickMixin._read_repos([str(here)], {}, set(), roots)
    assert got[str(here)]["ledger"]["entries"][0]["pickable"] == "yes"
    alone = TickMixin._read_repos([str(here)], {}, set())
    assert alone[str(here)]["ledger"]["entries"][0]["blocked_by"] == ["other#TD-002"], "the pass's own roots alone"


def test_a_for_you_entry_carries_added_answers_and_detail():
    """§4.4 *Repo facts* (TD-565, TD-736): every open entry's reading carries `added` (its `Added:` date)
    and `detail` (its **Why** and **Fix** paragraphs, clipped at `MAX_DETAIL_LINES`); a *for you* entry's
    carries `answers` and `default` too (its `**Answers:**` line in cadence §3.5's form, `\\|` a literal bar, the one
    ` (default)` marked — none when two are, as the board's reader gives it), and no other entry's."""
    fix = "\n".join(f"{n}. step" for n in range(1, 30))
    text = (
        "## TD-050: mine\n\n**Priority:** Low\n**Added:** 2026-10-07 (the designer)\n**Owner:** paul\n\n"
        "**Why:** the reason,\nover two lines.\n\n**Fix:**\n" + fix + "\n\n"
        "**Answers:** At the reset (default) | A fixed \\| time | Not now (default).\n\n"
        "## TD-051: a build\n\n**Owner:** grinder\n**Added:** 2026-10-07\n\n**Why:** x\n\n**Answers:** a | b\n\n"
        "## TD-052: bare\n\n**Blocked by:** decision (paul)\n"
    )
    mine, build, bare = ledger.entries(text)
    assert mine["added"] == "2026-10-07"
    assert mine["answers"] == ["At the reset", "A fixed | time", "Not now"]
    assert mine["default"] is None  # two marks: no single recommendation
    assert ledger.answers_of("Keep it (default) | Drop it.") == (["Keep it", "Drop it"], ["", ""], 0)
    # the field alone, in ledgerboard's split and mark (TD-585): a `Due:`/`Decided:` in it is words, the
    # default is the marked item's place, and a bare mark is no answer
    assert ledger.answers_of("Works. Due: 2026-01-01 | x") == (["Works. Due: 2026-01-01", "x"], ["", ""], None)
    assert ledger.answers_of("A | Decided: x (2026-01-01)") == (["A", "Decided: x (2026-01-01)"], ["", ""], None)
    assert ledger.answers_of("A | A (default)") == (["A", "A"], ["", ""], 1)
    assert ledger.answers_of("A | (default)") == (["A"], [""], None)
    # §4.10 *The answers' split* (TD-913): each split on its first ` — `, the mark read on the label
    assert ledger.answers_of("Keep it (default) — it ships Friday | Drop it — a — b") == (
        ["Keep it", "Drop it"],
        ["it ships Friday", "a — b"],
        0,
    )
    assert mine["consequences"] == ["", "", ""] and mine["ask"] == ""
    assert mine["detail"][:3] == ["**Why:** the reason,", "over two lines.", "**Fix:**"]
    assert len(mine["detail"]) == ledger.MAX_DETAIL_LINES
    assert not {"answers", "default"} & set(build)
    assert (build["added"], build["detail"]) == ("2026-10-07", ["**Why:** x"])
    assert (bare["added"], bare["answers"], bare["default"], bare["detail"]) == ("", [], None, [])


def test_a_decisions_words_after_its_dash_are_what_it_is_held_until():
    """§4.5a *Queue card: what needs the person* (TD-795): *held until <the words after the dash, as
    written>* — `until` on a *for you* entry's reading, '' where the decision has no words after it."""
    text = (
        "## TD-060: trial\n\n**Blocked by:** decision (paul) — after the trial\n\n"
        "## TD-061: bare\n\n**Blocked by:** TD-001, Decision (Paul)\n\n"
        "## TD-062: a build\n\n**Owner:** grinder\n"
    )
    trial, bare, build = ledger.entries(text)
    assert trial["until"] == "after the trial" and bare["until"] == ""
    assert "until" not in build  # not *for you*: no row reads it
    assert (
        ledger.until_of("decision (paul) – snoozed to 2026-10-21 (Paul); ask m-1")
        == "snoozed to 2026-10-21 (Paul); ask m-1"
    )
    assert ledger.until_of("decision (paul), TD-002") == ""  # a list going on past it: no words of its own
    assert ledger.until_of("TD-001") == ledger.until_of(None) == ""


def test_a_part_of_line_holds_its_parent_and_stays_out_of_blocked_by(tmp_path):
    """TD-1130 (ADR 2026-10-27 §2): pickable is ledgerboard's, so an open part holds its parent; the
    part is carried as `parts_open`, never in `blocked_by`, and a parent with open parts is *blocked*
    whatever its Kind. A part names its parent in `part_of`; an archived part of an open parent is in
    the reading's `archived`."""
    text = (
        "## TD-050: the design\n\n**Kind:** design-first\n\n"
        "## TD-051: a part\n\n**Kind:** build\n**Part of:** TD-50\n\n"
        "## TD-052: another part, blocked\n\n**Kind:** build\n**Part of:** TD-050\n**Blocked by:** TD-051\n\n"
        "## TD-053: a loose entry\n\n**Kind:** build\n\n"
        "## TD-054: a part of a finished parent\n\n**Kind:** build\n**Part of:** TD-049\n"
    )
    archive = (
        "## TD-049: done design\n\n**Kind:** design-first\n\n"
        "## TD-048: an archived part\n\n**Part of:** TD-050\n\n"
        "## TD-047: an archived part of an archived parent\n\n**Part of:** TD-049\n"
    )
    got = {e["id"]: e for e in ledger.entries(text, archive)}
    design, part, blocked = got["TD-050"], got["TD-051"], got["TD-052"]
    assert (design["pickable"], design["blocked_by"], design["parts_open"]) == ("no", [], ["TD-051", "TD-052"])
    assert design["for_page"] == "blocked" and design["part_of"] is None
    assert (part["pickable"], part["part_of"], part["parts_open"], part["for_page"]) == ("yes", "TD-50", [], "pickable")
    assert (blocked["pickable"], blocked["blocked_by"], blocked["for_page"]) == ("no", ["TD-051"], "blocked")
    assert (got["TD-053"]["part_of"], got["TD-053"]["parts_open"], got["TD-053"]["pickable"]) == (None, [], "yes")
    assert (got["TD-054"]["part_of"], got["TD-054"]["pickable"]) == ("TD-049", "yes")
    _repo(tmp_path / "r", text, archive)
    from datetime import UTC, datetime

    read = ledger.reading(tmp_path / "r", datetime.now(UTC), with_history=False)
    assert read["archived"] == ["TD-048"], "an archived part of an open parent; never one of an archived parent"
    assert read["by_kind"]["blocked"] == 2
