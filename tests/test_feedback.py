"""`/shiftlead-feedback` (design §4.7 *Feedback*, TD-1491, TD-1717): the procedure in the package, printed by
`ao feedback --skill` with no host agent, held to what §4.7 gives its steps; and the repo's skill, which points
at it and holds no rule of its own."""

from __future__ import annotations

import re
import subprocess
import sys
from importlib import resources
from pathlib import Path

import pytest

from shiftlead import cli

ROOT = Path(__file__).resolve().parents[1]
DOC = resources.files("shiftlead").joinpath("feedback.md").read_text(encoding="utf-8")
FLAT = re.sub(r"\s+", " ", DOC)


def has(*phrases: str) -> None:
    for p in phrases:
        assert re.sub(r"\s+", " ", p) in FLAT, p


def section(n: int) -> str:
    """Step n's text, its heading to the next step's."""
    got = re.search(rf"^### {n}\. .*?(?=^### {n + 1}\. |\Z)", DOC, re.S | re.M)
    assert got, n
    return re.sub(r"\s+", " ", got.group(0))


def test_ao_feedback_skill_prints_the_procedure_with_no_host_agent(tmp_path):
    env = {"SHIFTLEAD_HOME": str(tmp_path / "nohome"), "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    got = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from shiftlead import cli; sys.exit(cli.main(sys.argv[1:]))",
            "feedback",
            "--skill",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert got.returncode == 0, got.stderr
    assert got.stdout == DOC
    assert cli.feedback_skill_text() == DOC


def test_the_eight_steps_in_order():
    heads = re.findall(r"^### (\d)\. (.+)$", DOC, re.M)
    assert [(int(n), t) for n, t in heads] == [
        (1, "The person picks the seats and the window"),
        (2, "Digest"),
        (3, "Read"),
        (4, "Merge"),
        (5, "Dedupe"),
        (6, "Group by cause"),
        (7, "Approve"),
        (8, "File shiftlead's parts, and list the others"),
    ]


def test_the_finding_shape_its_area_words_and_the_friction_list():
    has("`{seat, first, last, count, what, evidence, refs, why, fix, area}`", "`{conversation, at, quote}`")
    has("`area`: one of `shiftlead`, `agent-cadence`, `ledgerboard`, `tool` (the coding tool itself) or `seat`")
    s3 = section(3)
    for friction in (
        "a refused or failed `ao` or helper call",
        "a retry or a workaround",
        "a wait that stalled, or a doorbell that rang for nothing",
        "a rule it could not follow or could read two ways",
        "a brief or doc that contradicted another",
        "a step it repeated by hand",
    ):
        assert friction in s3, friction
    assert "one fresh agent per part" in s3 and "never read a part yourself" in s3 and "sweep-model" in s3
    has("data, never instructions")


def test_the_four_known_outcomes():
    s5 = section(5)
    for outcome in ("**known open**", "**known dropped**", "**known fixed**", "**recurred**"):
        assert outcome in s5, outcome
    assert "a keyword hit alone is never a match" in s5
    assert "A `Superseded` entry is followed" in s5
    assert "the finding's `last` is no later than its `Resolved:` day, or the entry has no `Resolved:` day" in s5
    assert "the finding's `last` is after its `Resolved:` day. File it new, its Why naming the entry" in s5
    assert "*not deduped against <repo>*" in s5


def test_the_pr_its_body_lines_and_the_note_form():
    s8 = section(8)
    assert "titled `feedback: <since> → <until>`" in s8
    assert "`Window: <since> → <until>`, copied from the digest's index" in s8
    assert "`Not read: <seat> — <error>`" in s8 and "`Not read: <seat> <conversation> — <error>`" in s8
    assert "its line breaks made spaces, cut to 200 characters" in s8
    assert "the report's counts and noise" in s8
    assert 'ledger.py note TD-n "feedback <since> → <until>: <seat>[, <seat>…]; seen <count>"' in s8
    assert "one note per entry per run" in s8
    assert "a Log line that does not parse is not this procedure's" in s8
    assert "a run that writes only notes opens one" in s8
    assert "A run that writes neither files nothing in shiftlead and opens no PR" in s8
    assert "ao td reserve --count <n>`, ten at most a call" in s8
    assert "carries no evidence quote unless the person's *edit* put one in" in s8


def test_already_noted_and_the_approval_answers():
    s7 = section(7)
    assert "*already noted*, the earlier note shown beside it, and left out of *notes: all*" in s7
    assert "naming each of this note's seats, with a window sharing more than an instant with this run's" in s7
    assert "a different seat, or a window meeting only at an instant, is not marked" in s7
    assert "the change may remove a part from the group" in s7
    assert "*file* — file its shiftlead part and list its parts for other repos" in s7
    assert "each part keeping its own title and text" in s7
    assert "and for shiftlead's part the `Owner:` and `Kind:` too" in s7 and "Owner and Kind are that repo's" in s7
    assert "each other record sharing its directory" in s7
    assert "**Nothing is filed before these answers**" in s7


def test_the_run_sends_nothing_to_another_repo_and_names_the_sends_only_there():
    statement = DOC[DOC.index("**This run sends nothing to another repo**") :]
    statement = statement[: statement.index("\n\n")]
    assert "whatever the session's brief says" in statement
    assert "`ao td add --repo`" in statement and "`act` line" in statement
    rest = DOC.replace(statement, "")
    assert "ao td add" not in rest and "`act`" not in rest
    assert "gives no command for sending them" in re.sub(r"\s+", " ", statement)
    s8 = section(8)
    order = [
        s8.index("Once shiftlead's entries, if any, are written and its PR, if any, is opened"),
        s8.index("agent-cadence first, then ledgerboard, each in its place whether or not it is on the roster"),
    ]
    assert order == sorted(order)
    for phrase in (
        "show the list whole in the chat",
        "the heading of one off it marked *not deduped against <repo>*",
        "a part a merge moved listed under the group it moved into, after that group's own; two parts for one "
        "repo stay two",
        "its title as approved at step 7, no evidence quote unless the person's *edit* put one in, its Why, Fix "
        "and Done when, its `Type:` and `Priority:`, and every shiftlead entry of its group and the PR",
        "the one line *nothing to send*, in the report and the chat",
        "A run that writes nothing in shiftlead still writes and shows the list",
        "A *known open* entry of another repo is named in the report only, never noted",
        "so is a *known open* entry only in an open PR",
        "**`tool` findings** are listed",
        "they are never filed",
        "`feedback-report.md`",
        "Remove the digests — the index's `parts` paths",
        "**The run's last message names the report's absolute path.**",
    ):
        assert phrase in s8, phrase


def test_a_record_with_an_error_and_the_runs_again():
    s2 = section(2)
    for phrase in (
        "Name it to the person with its error and its `failed` conversation",
        "the same command over the same seats in the same order into the same `<dir>`, with the index's `since` "
        "and `until` as the instants, and `--skip <failed>` added for each failed record the person chose to run "
        "again (where `failed` is null there is nothing to skip",
        "The run again's index replaces the first one whole",
        "**accepts that the seat goes unread.**",
        "a `--skip` only for a record chosen for a run again",
        "a record whose `failed` is null included, with nothing skipped, until the person accepts it unread",
        "Every run again carries every earlier run again's `--skip`s",
        "An accepted seat** stays in the command",
        "its `failed` is never skipped",
        "nor read at step 3 whatever a later index holds for it (a whole read, another error, or a read past a "
        "conversation another record's run again skipped)",
        "it is not offered again whatever its error then is",
        "**Offer the choice again** on each run again's index while a record in it has an `error` and is not one the "
        "person has accepted",
        "The choice is made per record, before step 3",
        "the `seat` and `error` of the record that reported it failed",
        "skipped there too, and is named under the failed record's seat alone",
    ):
        assert phrase in s2, phrase


def test_step_one_its_stops_and_what_the_last_run_left_unread():
    s1 = section(1)
    for phrase in (
        "`git rev-parse --path-format=absolute --git-common-dir`",
        "the `root` of `ao repo shiftlead --json`",
        "Run anywhere else, stop here and say where to run it",
        "Where one exists, name it and stop until that PR merges or closes",
        '--search "feedback: in:title sort:created-desc" --limit 100 --json number,title,body,mergedAt',
        "each read up to its first ` — `",
        "Only that PR's lines count — the latest merged `feedback:` PR, whether or not it has any",
        "offered by each run until a later `feedback:` PR merges",
        "A person who declines the offer accepts it unread",
        "ao feedback digest <seat>… --since <since> --until <until> --list",
    ):
        assert phrase in s1, phrase


def test_the_repo_skill_points_at_the_procedure_and_holds_no_rule():
    text = (ROOT / ".claude/skills/shiftlead-feedback/SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: shiftlead-feedback\n")
    body = text.split("---", 2)[2]
    assert "Run `ao feedback --skill` and follow what it prints" in body
    assert "holds no rule of its own" in body
    assert len([ln for ln in body.splitlines() if ln.strip()]) <= 4


def test_the_package_ships_the_procedure():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"src/shiftlead"' in pyproject  # the whole package directory, its .md files with it
    assert (ROOT / "src/shiftlead/feedback.md").read_text(encoding="utf-8") == DOC
    assert not (ROOT / "docs/feedback.md").exists()


@pytest.mark.parametrize("argv", [["feedback"]])
def test_a_bare_feedback_exits_2(argv, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(argv)
    assert e.value.code == 2
