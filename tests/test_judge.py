"""The planted-defect sets and `pdm run judge`'s parts that need no tool (design §4.9b *A model's fitness, before
the role*, TD-1649): each set's shape, the mechanical match and its worked reply, the bar, the row, and a case's
scratch repository."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("judge", ROOT / "scripts" / "judge.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["judge"] = mod
    spec.loader.exec_module(mod)
    return mod


jd = _load()
CASES = jd.load_set("fact-checker")


def _has(commit: str) -> bool:
    return (
        subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=ROOT, capture_output=True).returncode == 0
    )


# --- the set's shape ------------------------------------------------------------------------------------------------


def test_the_fact_checkers_set_holds_its_counts():
    defects = sum(len(c.defects) for c in CASES)
    clean = sum(1 for c in CASES if not c.defects)
    assert len(CASES) >= 10 and defects >= 10 and clean >= 3, (len(CASES), defects, clean)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_a_case_has_its_shape(case, tmp_path):
    if not _has(case.pinned):
        pytest.skip(f"{case.pinned[:12]} is not in this clone (a shallow one); the precheck's full clone holds it")
    paths = jd.touched(case)
    assert paths, "the patch touches nothing"
    for p in paths:
        assert p.endswith(".md"), f"{p}: a case is a doc-only change"
        assert not any(p == s or p.startswith(s + "/") for s in jd.STRIPPED), f"{p}: the seat's repository strips it"
    added = [line for line in case.patch.read_text(encoding="utf-8").splitlines() if line.startswith("+")]
    for line in added:
        assert not any(s in line for s in jd.STRIPPED), f"an added line names a stripped directory: {line}"
        assert not re.search(r"\b[0-9a-f]{7,40}\b", line), f"an added line cites a sha: {line}"
    files = jd.patched(ROOT, case, tmp_path / "patched")  # raises where the patch does not apply to its commit
    ids = [d.id for d in case.defects]
    assert len(ids) == len(set(ids)), ids
    spans = [s for d in case.defects for s in d.spans()]
    for s in spans:
        size = jd.size_at_sha(ROOT, case, s.file, files)
        assert size is not None, f"{s.file}: not in the stripped tree at the pushed sha"
        assert 1 <= s.a <= s.b <= size, f"{s}: outside {s.file}'s {size} lines"
    for d in case.defects:
        assert d.at.file in files, f"{d.id}: a defect is in the patched file"
    by_file: dict[str, list] = {}
    for s in spans:
        by_file.setdefault(s.file, []).append(s)
    for f, ss in by_file.items():
        ss.sort(key=lambda s: s.a)
        for prev, nxt in zip(ss, ss[1:], strict=False):
            assert nxt.a - prev.b > jd.WIDEST, f"{f}: {prev} and {nxt} overlap or lie within {jd.WIDEST} lines"


# --- the match ------------------------------------------------------------------------------------------------------


def _worked() -> str:
    text = (ROOT / "tests" / "judgment" / "README.md").read_text(encoding="utf-8")
    return re.search(r"```text\n(.*?)```", text, re.S).group(1)


def test_the_readmes_worked_reply_scores_as_it_says(tmp_path):
    case = next(c for c in CASES if c.name == "02-tail-and-restarts")
    if not _has(case.pinned):
        pytest.skip(f"{case.pinned[:12]} is not in this clone")
    files = jd.patched(ROOT, case, tmp_path / "p")
    names = ["docs/glossary.md", "docs/design/6-policies.md", "README.md", "src/sessionorc/agent_common.py"]
    sizes = {n: jd.size_at_sha(ROOT, case, n, files) for n in names}
    got = jd.score(_worked(), case, sizes)
    assert got.answered and got.model == "gemini/gemini-3.5-flash-lite"
    assert (got.caught, got.missed, got.false, got.duplicates) == (["D1", "D2"], [], 1, 1)


def test_blocks_cut_at_top_level_markers_and_unindented_paragraphs():
    text = (
        "cadence-review: SHIP\n- one\n  more of one\n  - nested\n2. two\nlazy line of two\n\n"
        "para\n  indented\n\n- three"
    )
    assert jd.blocks(text) == [
        "- one\n  more of one\n  - nested",
        "2. two\nlazy line of two",
        "para\n  indented",
        "- three",
    ]


def test_a_location_is_a_full_path_and_a_range_that_reads():
    sizes = {"docs/a.md": 100, "src/b.py": 30}
    block = (
        "`docs/a.md:5`, (src/b.py:1-3). b/docs/a.md:9: ./src/b.py:2–4 a.md:5 10:30 localhost:8080 "
        "docs/a.md:9-5 docs/a.md:1-21 docs/a.md:101 docs/a.md:0"
    )
    got = [(s.file, s.a, s.b) for s in jd.locations(block, sizes)]
    assert got == [("docs/a.md", 5, 5), ("src/b.py", 1, 3), ("docs/a.md", 9, 9), ("src/b.py", 2, 4)]


def _case(*defects):
    return jd.Case("x", Path("."), "0" * 40, list(defects))


def test_no_verdict_line_is_none():
    got = jd.score("I think it holds.\n- docs/a.md:3 wrong", _case(), {"docs/a.md": 9})
    assert not got.answered and got.why.startswith("malformed")


def test_a_clean_ship_with_a_closing_sentence_has_no_false_finding():
    got = jd.score("cadence-review: SHIP · x/y · docs · 0 findings\n\nEvery claim holds.", _case(), {})
    assert got.answered and got.false == 0 and got.caught == [] and got.missed == []


def test_one_finding_catches_every_defect_it_meets_once():
    d1 = jd.Defect("D1", jd.Span("docs/a.md", 3, 3), "", [jd.Span("src/b.py", 10, 10)])
    d2 = jd.Defect("D2", jd.Span("docs/a.md", 40, 41), "", [])
    reply = "cadence-review: BLOCK\n- docs/a.md:3 and docs/a.md:41\n- src/b.py:10 again\n- docs/a.md:20 not one"
    got = jd.score(reply, _case(d1, d2), {"docs/a.md": 50, "src/b.py": 20})
    assert (got.caught, got.missed, got.duplicates, got.false) == (["D1", "D2"], [], 1, 1)


# --- the bar and the row --------------------------------------------------------------------------------------------


def _s(caught=0, missed=0, false=0, answered=True):
    return jd.Score(answered, caught=["c"] * caught, missed=["m"] * missed, false=false)


def test_the_bar():
    ten = [_s(caught=1) for _ in range(9)] + [_s(missed=1)]
    assert jd.tally(ten).passed  # one miss in ten
    assert not jd.tally([_s(caught=1) for _ in range(8)] + [_s(missed=1), _s(missed=1)]).passed
    false = [_s(caught=1, false=1), _s(caught=1, false=1)] + [_s(caught=1) for _ in range(8)]
    assert jd.tally(false).passed  # two cases with a false finding in ten answered
    assert not jd.tally([_s(caught=1, false=1)] * 3 + [_s(caught=1)] * 7).passed  # three in ten answered
    nones = [_s(answered=False)] * 2 + [_s(caught=1)] * 8
    assert jd.tally(nones).passed and not jd.tally([_s(answered=False)] * 3 + [_s(caught=1)] * 7).passed
    assert not jd.tally([_s(answered=False)] * 10).passed


def test_the_row():
    t = jd.tally([_s(caught=2, false=1), _s(answered=False)])
    assert jd.row("2026-11-14", "gemini-reader", "", t, 12.4) == (
        "| 2026-11-14 | gemini-reader | — | 2 | 0 | 1 | 1 | 12 | no |"
    )
    table = (ROOT / "docs" / "judgment" / "fact-checker.md").read_text(encoding="utf-8")
    assert jd.ROW_HEAD in table and "not a run" in table


def test_the_ask_is_one_fixed_text():
    assert jd.ask_text(3, "abc") == "fact-check PR #3 at abc: every claim the diff makes"


# --- a case's repository --------------------------------------------------------------------------------------------


def _repo(where: Path) -> str:
    def git(*a):
        return subprocess.run(["git", *a], cwd=where, check=True, capture_output=True, text=True).stdout.strip()

    where.mkdir()
    git("init", "-q", "-b", "main")
    (where / "docs").mkdir()
    (where / "docs" / "a.md").write_text("one\ntwo\n")
    (where / "tests" / "judgment").mkdir(parents=True)
    (where / "tests" / "judgment" / "answers.toml").write_text("secret\n")
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "pin")
    return git("rev-parse", "HEAD")


def test_a_case_repository_holds_no_history_and_the_same_sha_each_run(tmp_path):
    checkout = tmp_path / "checkout"
    pinned = _repo(checkout)
    d = tmp_path / "case"
    d.mkdir()
    (d / "case.toml").write_text(f'pinned = "{pinned}"\n')
    (d / "change.patch").write_text(
        "diff --git a/docs/a.md b/docs/a.md\n--- a/docs/a.md\n+++ b/docs/a.md\n@@ -1,2 +1,3 @@\n one\n two\n+three\n"
    )
    case = jd.load_case(d)
    clone, sha = jd.case_repo(checkout, case, tmp_path / "run1")
    _again, sha2 = jd.case_repo(checkout, case, tmp_path / "run2")
    assert sha == sha2

    def git(*a):
        return subprocess.run(["git", *a], cwd=clone, check=True, capture_output=True, text=True).stdout

    assert sorted(git("log", "--all", "--format=%s").split()) == sorted(["main", case.name + ":", "the", "change"])
    assert pinned not in git("log", "--all", "--format=%H")
    assert git("ls-tree", "-r", "--name-only", sha).split() == ["docs/a.md"]
    assert git("show", f"{sha}:docs/a.md") == "one\ntwo\nthree\n"
    assert git("diff", "--name-only", f"origin/main...{sha}").split() == ["docs/a.md"]
    assert jd.sizes_at(clone, sha) == {"docs/a.md": 3}
