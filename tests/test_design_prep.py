"""The pre-review script (design §4.9c *What a design's author prepares before a review*, TD-1755): each check
passing and failing on a scratch repo, the waivers, the exits, and the temporary worktree it leaves behind."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "design_prep.py"


def _load():
    spec = importlib.util.spec_from_file_location("design_prep", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["design_prep"] = mod  # a dataclass reads its module
    spec.loader.exec_module(mod)
    return mod


dp = _load()

INDEX = """# Design

- **§1** [Problem](design/1-problem.md) — the problem.
- **§4.9c** [Flows](design/4.9c-flows.md) — the flows.
"""

FLOWS = """# §4.9c Flows

**The gate: no reviewer reads a design the script has not passed at that commit.** It holds.

**The fact-check: a seat another tool fills (TD-1).** It reads.
"""

ENTRY = """## TD-1: The design

**Priority:** medium
**Status:** Open

**Fix:** Build `scripts/tool.py`, with:
- a test.

**Done when:** it is merged.
"""

BRIEF = "# Designer brief\n\nThe gate: no reviewer is sent a design that has not passed at the commit.\n"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A scratch repo whose base commit is `origin/main`: a design index, one section, a ledger entry, a brief."""
    for k, v in {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }.items():
        monkeypatch.setenv(k, v)
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    files = {
        "docs/design.md": INDEX,
        "docs/design/4.9c-flows.md": FLOWS,
        "docs/design/1-problem.md": "# §1\n\nText.\n",
        "docs/ledger/TD-1.md": ENTRY,
        "docs/briefs/designer.md": BRIEF,
        "src/a.py": "def f():\n    pass\n",
        "src/b.py": "x = 1\n",
    }
    for rel, text in files.items():
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text(text)
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base")
    _git(r, "update-ref", "refs/remotes/origin/main", "HEAD")
    monkeypatch.chdir(r)
    monkeypatch.setattr(dp, "run_tools", lambda tree, base: ([], []))
    monkeypatch.setattr(dp, "cadence_root", lambda tree: None)
    return r


def put(repo: Path, files: dict[str, str], commit: bool = True) -> None:
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    if commit:
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "change")


def run(capsys, *args: str) -> tuple[int, list[str]]:
    code = dp.main(["--entry", "TD-1", *args])
    return code, capsys.readouterr().out.strip().split("\n")


PREP = "docs/reviews/TD-1.prep.yml"
WAIVE_HEAD = "waive:\n  - check: rules\n    rule: the gate\n    file: docs/design/1-problem.md\n"
RULE = """rules:
  - name: the gate
    find: "(?i)no reviewer"
    terms: ["passed", "commit"]
"""


def test_pass_on_a_non_empty_changed_text(repo, capsys):
    put(
        repo,
        {
            "docs/design/4.9c-flows.md": FLOWS + "\nSee `src/a.py` and §4.9c *The gate* and TD-1.\n",
            PREP: RULE + 'claims:\n  - says: f is defined\n    at: src/a.py:1\n    has: "def f"\n',
        },
    )
    code, out = run(capsys)
    assert code == 0, out
    assert out[0].startswith("design-prep: PASS · TD-1 · ")
    assert out[0].endswith("· claims 1 · rules 1 · new 0 · waived 0")


def test_a_rule_term_changed_in_one_place_fails_naming_that_paragraph(repo, capsys):
    put(repo, {"docs/briefs/designer.md": BRIEF.replace("passed", "cleared"), PREP: RULE})
    code, out = run(capsys)
    assert code == 1
    assert out[0].startswith("design-prep: FAIL · TD-1")
    assert len(out) == 2
    assert out[1].startswith("rules · docs/briefs/designer.md:3 · the gate: missing passed · The gate: no reviewer")


def test_a_phrase_wrapped_across_lines_still_matches(repo, capsys):
    put(
        repo,
        {
            "docs/briefs/designer.md": "# B\n\nThe gate: no\nreviewer is sent a design not passed at the\ncommit.\n",
            PREP: RULE,
        },
    )
    assert run(capsys)[0] == 0


def test_a_rule_declared_but_not_repeated_is_a_flag(repo, capsys):
    put(repo, {PREP: RULE.replace("(?i)no reviewer", "only here once")})
    code, out = run(capsys)
    assert code == 1
    assert out[1] == f"rules · {PREP}:2 · the gate: declared but not repeated (0 paragraph(s) match its find)"


def test_terms_are_whole_words(repo, capsys):
    put(
        repo,
        {"docs/briefs/designer.md": BRIEF.replace("passed", "bypassed"), PREP: RULE.replace('"passed"', '"passed"')},
    )
    code, out = run(capsys)
    assert code == 1 and "missing passed" in out[1]


def test_a_glossary_list_is_read_item_by_item(repo, capsys):
    gloss = (
        "# Glossary\n\n- **gate**: no reviewer reads it unless passed at the commit.\n"
        "- **pass**: no reviewer\n  sees it.\n"
    )
    put(repo, {"docs/glossary.md": gloss, PREP: RULE})
    code, out = run(capsys)
    assert code == 1
    assert [ln.split(" · ")[1] for ln in out[1:]] == ["docs/glossary.md:4"]


def test_a_fix_with_bullets_is_one_paragraph(repo, capsys):
    entry = ENTRY.replace("- a test.", "- no reviewer reads it\n- unless passed at the commit.")
    put(repo, {"docs/ledger/TD-1.md": entry, PREP: RULE})
    assert run(capsys)[0] == 0


def test_a_fenced_block_is_read_by_no_check(repo, capsys):
    put(
        repo,
        {"docs/design/1-problem.md": "# §1\n\n```\nno reviewer, nothing else; see missing/file.py\n```\n", PREP: RULE},
    )
    assert run(capsys)[0] == 0


def test_a_waiver_on_one_paragraph_leaves_another_drift_flagged(repo, capsys):
    text = "# P\n\nNo reviewer is shown this text in any of the cases that we list.\n\nNo reviewer sees it again.\n"
    waive = (
        "waive:\n  - check: rules\n    rule: the gate\n    file: docs/design/1-problem.md\n"
        '    text: "No reviewer is shown this text in any"\n    why: another rule\n'
    )
    put(repo, {"docs/design/1-problem.md": text, PREP: RULE + waive})
    code, out = run(capsys)
    assert code == 1
    assert [ln.split(" · ")[1] for ln in out[1:]] == ["docs/design/1-problem.md:5"]


def test_a_short_paragraph_waiver_is_not_prepared(repo, capsys):
    text = "# P\n\nNo reviewer is shown this text in any of the cases that we list.\n"
    waive = WAIVE_HEAD + "    text: No reviewer is shown\n"
    put(repo, {"docs/design/1-problem.md": text, PREP: RULE + waive})
    code, out = run(capsys)
    assert code == 2 and out[0].startswith("design-prep: NOT PREPARED · waive item 1")


def test_a_short_waiver_naming_the_whole_paragraph_is_allowed(repo, capsys):
    text = "# P\n\nNo reviewer here.\n"
    waive = WAIVE_HEAD + "    text: No reviewer here.\n"
    put(repo, {"docs/design/1-problem.md": text, PREP: RULE + waive})
    code, out = run(capsys)
    assert code == 0, out
    assert out[0].endswith("waived 1")


def test_a_not_repeated_flag_is_hidden_by_a_waiver_naming_the_rule(repo, capsys):
    rule = RULE.replace("(?i)no reviewer", "only here once")
    waive = f"waive:\n  - check: rules\n    file: {PREP}\n    text: the gate\n    why: said once on purpose\n"
    put(repo, {PREP: rule + waive})
    code, out = run(capsys)
    assert code == 0, out


def test_a_rule_waiver_leaves_another_rules_flag_on_the_same_paragraph(repo, capsys):
    rules = RULE + '  - name: the other\n    find: "(?i)no reviewer"\n    terms: ["design"]\n'
    text = "# P\n\nNo reviewer is shown this text in any of the cases that we list.\n"
    waive = (
        "waive:\n  - check: rules\n    rule: the gate\n    file: docs/design/1-problem.md\n"
        '    text: "No reviewer is shown this text in any"\n'
    )
    put(repo, {"docs/design/1-problem.md": text, PREP: rules + waive})
    code, out = run(capsys)
    assert code == 1
    assert [ln.split(" · ")[2].split(":")[0] for ln in out[1:]] == ["the other"]


def test_a_waiver_hides_two_flags_and_a_stale_one_is_a_flag(repo, capsys):
    text = "# P\n\nSee gone/x.py here.\n\nAnd gone/x.py there.\n"
    waive = (
        "waive:\n  - check: claims\n    file: docs/design/1-problem.md\n    text: gone/x.py\n"
        "  - check: pointers\n    file: docs/design/1-problem.md\n    text: TD-99\n"
    )
    put(repo, {"docs/design/1-problem.md": text, PREP: waive})
    code, out = run(capsys)
    assert code == 1
    assert out[0].endswith("flags 1")
    assert out[1].startswith(f"waive · {PREP}:")
    assert "hides no flag: pointers · docs/design/1-problem.md · TD-99" in out[1]


def test_claims_at_line_and_has(repo, capsys):
    prep = (
        "claims:\n  - says: too far\n    at: src/a.py:9\n  - says: wrong text\n    at: src/a.py\n    has: def g\n"
        "  - says: missing\n    at: src/nope.py\n"
    )
    put(repo, {PREP: prep})
    code, out = run(capsys)
    assert code == 1
    assert out[1:] == [
        f"claims · {PREP}:2 · too far: src/a.py has 2 lines, not line 9",
        f"claims · {PREP}:4 · wrong text: src/a.py does not hold 'def g'",
        f"claims · {PREP}:7 · missing: src/nope.py does not exist at the commit",
    ]


def test_a_count_by_files_and_by_lines(repo, capsys):
    prep = (
        'claims:\n  - says: two sources\n    count: {glob: "src/*.py"}\n    is: 2\n'
        '  - says: one defines\n    count: {glob: "src/**/*.py", grep: "^def "}\n    is: 1\n'
        '  - says: three lines\n    count: {glob: "src/*.py", lines: true}\n    is: 3\n'
        '  - says: wrong\n    count: {glob: "src/*.py", grep: "pass", lines: true}\n    is: 5\n'
    )
    put(repo, {PREP: prep})
    code, out = run(capsys)
    assert code == 1
    assert out[1:] == [f"claims · {PREP}:11 · wrong: count of src/*.py is 1, not 5"]


def test_paths_in_the_changed_text(repo, capsys):
    text = (
        "# P\n\nSee src/a.py:2, src/b.py. And [x](../ledger/TD-1.md) and ~/home/x.py and /abs/x.py and "
        "https://e.com/x/y.md and `docs/reviews/TD-<n>.prep.yml` and src/*.py and src/gone.py.\n"
    )
    put(repo, {"docs/design/1-problem.md": text, PREP: ""})
    code, out = run(capsys)
    assert code == 1
    assert out[1:] == ["claims · docs/design/1-problem.md:3 · src/gone.py does not exist at the commit"]


def test_a_path_on_an_unchanged_line_is_not_read(repo, capsys):
    put(repo, {"docs/design/1-problem.md": "# §1\n\nSee src/gone.py.\n"}, commit=True)
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    put(repo, {PREP: ""})
    assert run(capsys)[0] == 0


def test_a_new_path_with_and_without_its_build_and_once_it_exists(repo, capsys):
    text = "# P\n\nThe build writes scripts/tool.py and scripts/other.py.\n"
    prep = "new:\n  - path: scripts/tool.py\n    by: TD-1\n  - path: scripts/other.py\n    by: TD-1\n"
    put(repo, {"docs/design/1-problem.md": text, PREP: prep})
    code, out = run(capsys)
    assert code == 1
    assert out[1:] == [f"claims · {PREP}:4 · scripts/other.py: TD-1's Fix does not name it"]
    put(
        repo,
        {
            "scripts/tool.py": "",
            "docs/design/1-problem.md": "# P\n\nThe build writes scripts/tool.py.\n",
            PREP: "new:\n  - path: scripts/tool.py\n    by: TD-1\n",
        },
    )
    code, out = run(capsys)
    assert out[1:] == [f"claims · {PREP}:2 · scripts/tool.py: a new path that exists now; drop the item"]


def test_pointers(repo, capsys):
    text = (
        "# P\n\n§4.9c *The gate*, §4.9c *The fact-check* and §4.9c *The fact-check: a seat another tool fills.* "
        "hold; §4.9c *No such* does not; §7 is not indexed; cadence §4.8, §9 and §12 are skipped; "
        "[ADR](x.md) §3 and `cadence.md` §5 too; TD-1 is filed, TD-99 is not.\n"
    )
    put(repo, {"docs/design/1-problem.md": text, PREP: ""})
    code, out = run(capsys)
    assert code == 1
    assert [ln.split(" · ", 2)[2] for ln in out[1:]] == [
        "§4.9c *No such*: no lead or heading of docs/design/4.9c-flows.md reads 'No such'",
        "§7: §7 is not in docs/design.md's index",
        "TD-99 is not in the ledger, its archive, or the PR",
    ]


def test_a_title_cited_without_its_full_stop(repo, capsys):
    put(repo, {"docs/design/4.9c-flows.md": FLOWS + "\n**Short lead.** body\n\nSee §4.9c *Short lead*.\n", PREP: ""})
    assert run(capsys)[0] == 0


def test_a_ledger_entry_filed_by_the_pr_counts(repo, capsys):
    put(
        repo,
        {
            "docs/ledger/TD-2.md": ENTRY.replace("TD-1", "TD-2").replace("scripts/tool.py", "src/a.py"),
            "docs/design/1-problem.md": "# §1\n\nTD-2 builds it.\n",
            PREP: "",
        },
    )
    code, out = run(capsys)
    assert code == 0, out


def test_flags_with_a_tool_that_could_not_run_is_a_fail(repo, capsys, monkeypatch):
    monkeypatch.setattr(dp, "run_tools", lambda tree, base: ([], ["ledger check: timed out after 300 s"]))
    put(repo, {PREP: "claims:\n  - says: x\n    at: src/nope.py\n"})
    code, out = run(capsys)
    assert code == 1
    assert out[-1] == "tools · could not run · ledger check: timed out after 300 s"


def test_a_tool_that_could_not_run_alone_is_cannot_run(repo, capsys, monkeypatch):
    monkeypatch.setattr(dp, "run_tools", lambda tree, base: ([], ["doc-bound tests: pytest exit 4"]))
    put(repo, {PREP: ""})
    code, out = run(capsys)
    assert code == 3
    assert out[0].startswith("design-prep: CANNOT RUN · TD-1 · ") and out[0].endswith("doc-bound tests: pytest exit 4")


def test_a_tool_flag_can_be_waived(repo, capsys, monkeypatch):
    flag = dp.Flag("tools", "tests/test_x.py", 3, "test_y", "test_y failed")
    monkeypatch.setattr(dp, "run_tools", lambda tree, base: ([flag], []))
    put(repo, {PREP: "waive:\n  - check: tools\n    file: tests/test_x.py\n    text: test_y\n"})
    code, out = run(capsys)
    assert code == 0 and out[0].endswith("waived 1")


def test_a_dirty_work_tree_and_an_untracked_design_file_are_not_prepared(repo, capsys):
    put(repo, {PREP: ""})
    (repo / "docs/design/1-problem.md").write_text("changed\n")
    code, out = run(capsys)
    assert code == 2 and "docs/design/1-problem.md" in out[0]
    _git(repo, "checkout", "--", "docs/design/1-problem.md")
    (repo / "docs/design/new.md").write_text("new\n")
    code, out = run(capsys)
    assert code == 2 and "docs/design/new.md" in out[0]
    assert run(capsys, "--rev", "HEAD~0")[0] == 0  # another rev is read at the commit, the work tree aside


def test_advisory_exits_0_on_a_fail(repo, capsys):
    put(repo, {PREP: "claims:\n  - says: x\n    at: src/nope.py\n"})
    code, out = run(capsys, "--advisory")
    assert code == 0
    assert out[0].startswith("design-prep: ADVISORY · FAIL · TD-1")
    assert out[1].startswith("claims · ")


def test_rev_leaves_no_worktree_and_a_stale_one_is_pruned(repo, capsys, tmp_path):
    put(repo, {PREP: ""})
    stale = tmp_path / "design-prep-stale"
    other = tmp_path / "keep-me"
    _git(repo, "worktree", "add", "-q", "--detach", str(stale), "HEAD")
    _git(repo, "worktree", "add", "-q", "--detach", str(other), "HEAD")
    import shutil

    shutil.rmtree(stale)
    shutil.rmtree(other)
    assert run(capsys, "--rev", "HEAD")[0] == 0
    listed = _git(repo, "worktree", "list", "--porcelain")
    assert "design-prep-" not in listed
    assert str(other) in listed  # another's prunable worktree is never touched


@pytest.mark.parametrize(
    "prep, why",
    [
        (None, "no docs/reviews/TD-1.prep.yml at "),
        ("claims: [\n", "is not YAML"),
        ("extra: []\n", "unknown key: extra"),
        ("claims:\n  - says: x\n", "needs one of at or count"),
        ("claims:\n  - says: x\n    at: a\n    count: {glob: a}\n    is: 1\n", "needs one of at or count"),
        ("claims:\n  - says: x\n    count: {glob: a}\n", "integer is"),
        ("claims:\n  - says: x\n    at: a\n    bogus: 1\n", "unknown key: bogus"),
        ('rules:\n  - name: r\n    find: "("\n    terms: [a]\n', "find is not a regex"),
        ("rules:\n  - name: r\n    find: a\n    terms: []\n", "terms is not a list"),
        ("new:\n  - path: a.py\n    by: nobody\n", "by is not a TD-<n>"),
        ("waive:\n  - check: style\n    file: a\n    text: b\n", "check is not one of"),
        ("waive:\n  - check: rules\n    file: docs/design/1-problem.md\n    text: b c d e f g h i\n", "names no rule"),
    ],
)
def test_each_not_prepared_cause(repo, capsys, prep, why):
    if prep is not None:
        put(repo, {PREP: prep})
    code, out = run(capsys)
    assert code == 2, out
    assert out[0].startswith("design-prep: NOT PREPARED · ") and why in out[0]


def test_each_cannot_run_cause(repo, capsys, monkeypatch):
    put(repo, {PREP: ""})
    code, out = run(capsys, "--rev", "nosuchref")
    assert code == 3 and out[0] == "design-prep: CANNOT RUN · cannot resolve --rev nosuchref"
    code, out = run(capsys, "--base", "nosuchbase")
    assert code == 3 and out[0] == "design-prep: CANNOT RUN · cannot resolve --base nosuchbase"
    _git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    code, out = run(capsys)
    assert code == 3 and "no merge base with origin/main" in out[0]
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD~1")

    def boom(*a):
        raise RuntimeError("oops")

    monkeypatch.setattr(dp, "check_pointers", boom)
    code, out = run(capsys)
    assert code == 3 and out[0] == "design-prep: CANNOT RUN · crash: RuntimeError: oops"


def test_the_tools_read_the_ledger_check_and_pytest(tmp_path, monkeypatch):
    """run_tools: a ledger error on an entry, a failing test by its def line, and tools that will not start."""
    (tmp_path / "docs/ledger").mkdir(parents=True)
    (tmp_path / "docs/ledger/TD-5.md").write_text("x\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_design_doc.py").write_text("import os\n\ndef test_b():\n    pass\n")
    ledger_out = (
        '{"flags": [{"level": "error", "id": "TD-5", "text": "⚠ TD-5: bad", "standing": false},'
        '{"level": "error", "id": "TD-6", "text": "⚠ TD-6: old", "standing": true},'
        '{"level": "info", "id": "TD-5", "text": "ℹ fine", "standing": false}]}'
    )
    pytest_out = "FAILED tests/test_design_doc.py::test_b - assert 0\n1 failed\n"

    def fake(cmd, **kw):
        if cmd[0] == "agent-cadence":
            return subprocess.CompletedProcess(cmd, 1, ledger_out, "")
        return subprocess.CompletedProcess(cmd, 1, pytest_out, "")

    monkeypatch.setattr(dp.subprocess, "run", fake)
    flags, cnr = dp.run_tools(tmp_path, "abc")
    assert [f.render() for f in flags] == [
        "tools · docs/ledger/TD-5.md:1 · ⚠ TD-5: bad",
        "tools · tests/test_design_doc.py:3 · test_b failed",
    ]
    assert cnr == []

    def gone(cmd, **kw):
        if cmd[0] == "agent-cadence":
            raise FileNotFoundError(cmd[0])
        raise subprocess.TimeoutExpired(cmd, 300)

    monkeypatch.setattr(dp.subprocess, "run", gone)
    flags, cnr = dp.run_tools(tmp_path, "abc")
    assert flags == [] and cnr == [
        "ledger check: agent-cadence will not start",
        "doc-bound tests: timed out after 300 s",
    ]

    def odd(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0 if cmd[0] == "agent-cadence" else 4, "{}", "")

    monkeypatch.setattr(dp.subprocess, "run", odd)
    assert dp.run_tools(tmp_path, "abc") == ([], ["doc-bound tests: pytest exit 4"])


def test_the_script_runs_as_a_command(repo):
    """Run as `python scripts/design_prep.py`: the first line of what it prints is the pass line."""
    put(repo, {PREP: ""})
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--entry", "TD-1", "--rev", "nosuchref"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 3 and r.stdout.startswith("design-prep: CANNOT RUN · ")
