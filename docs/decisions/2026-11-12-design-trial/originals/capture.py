"""The three replayed originals' turns (TD-1773, design §4.9c *The trial of the new shape*), captured before their
transcripts are pruned, by the cost model's `extract.py` and its Method step 2 (`tables.py select`).

    python extract.py ~/.claude/projects/-home-kmaster-shiftlead--claude-worktrees-designer-ao-1 > all.csv
    python capture.py all.csv     # writes turns.csv beside this file
    python capture.py             # prints each original designer's main-thread turns from turns.csv

A design's branches are those of the design PRs its key's rounds ran in (`Design PR:`, each PR's head branch):
TD-1470's rounds 1 to 8 only, its Hold revision (TD-1571, #3330) left out.
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
TURNS = HERE / "turns.csv"
MODEL = HERE.parents[1] / "2026-11-12-design-cost-model" / "tables.py"

DESIGNS = {
    "TD-1557": {"rounds": 3, "branches": ["td1557-design"]},  # #3511
    "TD-1569": {"rounds": 4, "branches": ["td-1569-design"]},  # #3465
    "TD-1470": {
        "rounds": 8,
        # #3107, #3152, #3189, #3226, #3246; no transcript line on this machine carries #3226's branch
        "branches": ["td1470-stuck-work", "td-1511-round5", "td-1525-round6", "td1534-td1470-round7", "td1553-design"],
    },
}


def _model():
    spec = importlib.util.spec_from_file_location("cost_tables", MODEL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DESIGNS, mod.TURNS = DESIGNS, TURNS
    return mod


def report() -> None:
    rows = list(csv.DictReader(TURNS.open()))
    print("design,main_turns,reviewer_turns,main_turns_by_branch")
    for td in DESIGNS:
        mine = [r for r in rows if r["design"] == td]
        main = [r for r in mine if r["phase"] not in ("reviewer", "report")]
        rev = [r for r in mine if r["phase"] == "reviewer"]
        by = Counter(r["branch"] for r in main)
        print(f"{td},{len(main)},{len(rev)},{' '.join(f'{b}={n}' for b, n in sorted(by.items()))}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        _model().select(Path(sys.argv[1]))
    report()
