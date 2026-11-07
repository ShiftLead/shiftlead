"""A design's synopsis (design §4.9c *The designer writes the synopsis*, §4.5 screen 6 *A design links its synopsis*,
TD-1537): every `docs/synopses/TD-<n>.md` keeps the shape and the plain-words rule `docs/synopses/README.md` states."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SYNOPSES = ROOT / "docs" / "synopses"
LEDGER = ROOT / "docs" / "ledger"

SECTIONS = ["What it does", "The key choices, and why", "What it rules out", "What you will see"]
MAX_LINES = 40
MAX_COLUMNS = 120

FINDING = re.compile(r"\bF\d+\b")
# `:<digits>` after a word holding a `/` or ending in a file extension: a path's line reference.
LINE_REF = re.compile(r"(\S+):\d+")
EXTENSION = re.compile(r"\.[A-Za-z][A-Za-z0-9]*$")


def problems(name: str, text: str, ledger_ids: set[str]) -> list[str]:
    """What is wrong with the synopsis `name` (its file name) holding `text`, against the ledger's ids."""
    out: list[str] = []
    m = re.fullmatch(r"(TD-\d+)\.md", name)
    if not m:
        return [f"{name}: a synopsis is named TD-<n>.md"]
    tid = m.group(1)
    if tid not in ledger_ids:
        out.append(f"{name}: the ledger holds no {tid}, open or archived")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines or not lines[0].startswith(f"# {tid}: "):
        out.append(f"{name}: the first line is `# {tid}: <the entry's title>`")
    heads = [ln[3:].strip() for ln in lines if ln.startswith("## ")]
    if heads != SECTIONS:
        out.append(f"{name}: its sections are {heads}, not {SECTIONS} in that order")
    if len(lines) > MAX_LINES:
        out.append(f"{name}: {len(lines)} non-blank lines, over {MAX_LINES}")
    for i, ln in enumerate(text.splitlines(), 1):
        if len(ln) > MAX_COLUMNS:
            out.append(f"{name}:{i} is {len(ln)} columns, over {MAX_COLUMNS}")
        if FINDING.search(ln):
            out.append(f"{name}:{i} names a finding id")
        if "`" in ln:
            out.append(f"{name}:{i} has a backtick")
        if ".py" in ln:
            out.append(f"{name}:{i} names a .py file")
        for word in LINE_REF.findall(ln):
            if "/" in word or EXTENSION.search(word):
                out.append(f"{name}:{i} has a line reference ({word}:…)")
    return out


def _ledger_ids() -> set[str]:
    return {p.stem for p in (*LEDGER.glob("TD-*.md"), *(LEDGER / "archive").glob("TD-*.md"))}


def _synopses() -> list[Path]:
    return sorted(p for p in SYNOPSES.glob("*.md") if p.name != "README.md")


def test_the_readme_states_the_shape_and_the_rule():
    readme = (SYNOPSES / "README.md").read_text()
    for section in SECTIONS:
        assert f"## {section}" in readme or f"*{section}*" in readme, section
    assert str(MAX_LINES) in readme and str(MAX_COLUMNS) in readme


def test_there_are_synopses():
    assert _synopses(), "docs/synopses/ holds no synopsis"


@pytest.mark.parametrize("path", _synopses(), ids=lambda p: p.name)
def test_every_synopsis_keeps_the_shape_and_the_rule(path):
    assert problems(path.name, path.read_text(), _ledger_ids()) == []


GOOD = """# TD-7: A seat as an ordered pool

## What it does

Each member is a separate record.

## The key choices, and why

- Members show on the team as seats.

## What it rules out

Pools only on question seats.

## What you will see

Later members carry a backup indicator, at 3:20 as at any time.
"""


def test_a_good_synopsis_passes_and_the_title_is_not_compared():
    assert problems("TD-7.md", GOOD, {"TD-7"}) == []
    assert problems("TD-7.md", GOOD.replace("A seat as an ordered pool", "Retitled"), {"TD-7"}) == []


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (lambda t: t.replace("# TD-7: ", "# TD-8: "), "first line"),
        (lambda t: t.replace("# TD-7: A seat", "# A seat"), "first line"),
        (lambda t: t.replace("## What it rules out", "## What it leaves out"), "sections"),
        (
            lambda t: t.replace("## What it rules out\n\nPools only on question seats.\n\n", "")
            + "\n## What it rules out\n\nPools.\n",
            "sections",
        ),
        (lambda t: t + "\n".join(f"line {i}" for i in range(40)), "non-blank lines"),
        (lambda t: t + "\n" + "x" * 121 + "\n", "columns"),
        (lambda t: t + "\nIt answers F12.\n", "finding id"),
        (lambda t: t + "\nIt reads `seat_able`.\n", "backtick"),
        (lambda t: t + "\nIt lives in queue.py now.\n", ".py"),
        (lambda t: t + "\nSee src/sessionorc/queue:120 for it.\n", "line reference"),
        (lambda t: t + "\nSee design.md:12 for it.\n", "line reference"),
    ],
)
def test_a_synopsis_breaking_a_rule_fails(change, says):
    found = problems("TD-7.md", change(GOOD), {"TD-7"})
    assert any(says in p for p in found), found


def test_a_synopsis_for_an_id_the_ledger_does_not_hold_fails():
    assert any("holds no TD-7" in p for p in problems("TD-7.md", GOOD, {"TD-8"}))
