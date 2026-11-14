"""The trial's baseline (TD-1775, design §4.9c *The trial of the new shape*, *The baseline*): the ten designs with a
`Source: rounds` record whose last design PR merged last before TD-1756's merge (#3682, 2026-11-13T06:05:21Z),
leaving out the three replayed (TD-1557, TD-1569, TD-1470) and the shape's own designs (TD-1720, TD-1721, TD-1722)
and the plan they are parts of, TD-1711 (#3524; the techlead's reply m-effae5549771, 2026-11-13).
Their turns are captured before the transcripts are pruned, by the cost model's `extract.py` and its Method step 2
(`tables.py select`), as `../originals/capture.py` captured the three originals'.

    for d in ~/.claude/projects/*shiftlead* ~/.claude-conformance/projects/*shiftlead*; do
        python ../../2026-11-12-design-cost-model/extract.py "$d"; done > all.csv   # one header kept
    python capture.py select all.csv   # writes turns.csv beside this file
    python capture.py sizes            # writes sizes.csv from git (each design PR's squash commit)
    python capture.py                  # prints the cost and size tables from turns.csv and sizes.csv

A design's branches are the head branches of the PRs in its entry's `Design PR:` (a bought round's or a Hold
revision's PR among them). The ten are fixed at this measurement: a later design PR of one of them is reported, not
counted.
"""

from __future__ import annotations

import csv
import importlib.util
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TURNS = HERE / "turns.csv"
SIZES = HERE / "sizes.csv"
MODEL = HERE.parents[1] / "2026-11-12-design-cost-model" / "tables.py"
SIZED = ("docs/design/", "docs/ledger/", "docs/synopses/")

# Each design's PRs, in its entry's `Design PR:` order: (number, head branch, squash commit), newest design first
# by its last PR's merge.
DESIGNS = {
    "TD-1550": [
        (3386, "td1550-design", "9a2bcc049"),
        (3487, "td-1675-round5", "4bf6fe191"),
        (3575, "td1707-design", "e23001076"),
        (3590, "td1732-round", "9eaf850de"),
    ],
    "TD-1573": [(3497, "td1573-design", "695d11661"), (3574, "td1703-design", "493c48d29")],
    "TD-1671": [(3570, "td1671-design", "8cbf19a74")],
    "TD-1650": [(3569, "td1650-design", "5d1d4b24f")],
    "TD-1567": [(3567, "td1567-design", "24b6927f7")],
    "TD-1543": [
        (3367, "td1543-design-have-a-session-do-it", "9e0f0077a"),
        (3492, "td-1676-round9", "2963a356d"),
        (3525, "td1702-round10", "109e7fbfb"),
        (3542, "td1708-round11", "813bd94e1"),
    ],
    "TD-1590": [(3526, "td1590-design", "5af501b40")],
    "TD-1568": [(3516, "td1568-design", "bb4e3641c")],
    "TD-1556": [(3504, "td1556-design", "cecdf508b")],
    "TD-1577": [
        (3410, "td1577-design", "68b573d72"),
        (3456, "td-1652-round5", "f9fbc3dac"),
        (3477, "td-1673-round6", "e6ea43b68"),
    ],
}


def _model():
    spec = importlib.util.spec_from_file_location("cost_tables", MODEL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DESIGNS = {td: {"branches": [b for _, b, _ in prs]} for td, prs in DESIGNS.items()}
    mod.TURNS = TURNS
    return mod


def select(src: Path) -> None:
    """`tables.py select` one design at a time: it phases the rows it picks in place, so a turn two designs share
    (a session's launch-branch turns between them) would reach the second already phased."""
    model, out, fields = _model(), [], None
    part = HERE / "turns.part.csv"
    try:
        for td, prs in DESIGNS.items():
            model.DESIGNS, model.TURNS = {td: {"branches": [b for _, b, _ in prs]}}, part
            model.select(src)
            with part.open() as f:
                r = csv.DictReader(f)
                fields = r.fieldnames
                out += list(r)
    finally:
        part.unlink(missing_ok=True)
    out, shared = one_design_each(out)
    with TURNS.open("w", newline="") as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows(out)
    print(f"{len(out)} rows written to {TURNS.name}; {shared} turns two designs picked, each kept once")


def one_design_each(rows: list[dict]) -> tuple[list[dict], int]:
    """Each turn counted under one design. One session works several designs' branches in turn, so `select`, run
    a design at a time, picks a reviewer whose first turn falls in two designs' windows, and a launch-branch turn
    between them, for both. Such a turn goes to the design whose branches hold its own branch; a reviewer on a
    launch branch, to the design that holds most of its own rows' branches; a turn left over, to the design of its
    session's next turn on a design's branch, else its last."""
    owner = {b: td for td, prs in DESIGNS.items() for _, b, _ in prs}
    key = lambda r: (r["session"], r["side"], r["msg"], r["ts"])  # noqa: E731
    picked: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        picked[key(r)].append(r)
    side_vote: dict[tuple, Counter] = defaultdict(Counter)
    for r in rows:
        if r["side"] and r["branch"] in owner:
            side_vote[(r["session"], r["side"])][owner[r["branch"]]] += 1
    mains = defaultdict(list)  # a session's own turns on a design's branch, in time order
    for r in rows:
        if not r["side"] and r["branch"] in owner:
            mains[r["session"]].append((r["ts"], owner[r["branch"]]))
    for v in mains.values():
        v.sort()

    def choose(rs: list[dict]) -> str:
        r, claim = rs[0], {x["design"] for x in rs}
        if owner.get(r["branch"]) in claim:
            return owner[r["branch"]]
        vote = side_vote.get((r["session"], r["side"]))
        if vote:
            best = [td for td, _ in vote.most_common() if td in claim]
            if best:
                return best[0]
        later = [td for ts, td in mains[r["session"]] if ts >= r["ts"] and td in claim]
        earlier = [td for ts, td in mains[r["session"]] if ts < r["ts"] and td in claim]
        return (later or earlier[-1:] or sorted(claim))[0]

    out, shared = [], 0
    for r in rows:
        rs = picked[key(r)]
        if len(rs) == 1:
            out.append(r)
        elif r is rs[0]:
            shared += 1
            td = choose(rs)
            out.append(next(x for x in rs if x["design"] == td))
    return out, shared


def sizes() -> None:
    """Each design PR's additions under docs/design/, docs/ledger/ and docs/synopses/, by `git show --numstat`."""
    out = []
    for td, prs in DESIGNS.items():
        for pr, _, sha in prs:
            text = subprocess.run(
                ["git", "show", "--numstat", "--format=", sha], capture_output=True, text=True, check=True
            ).stdout
            add = defaultdict(int)
            for line in text.splitlines():
                a, _, path = line.split("\t", 2)
                for d in SIZED:
                    if path.startswith(d) and a != "-":
                        add[d] += int(a)
            out.append(
                {"design": td, "pr": pr, "commit": sha}
                | {"design_lines": add[SIZED[0]], "ledger": add[SIZED[1]], "synopses": add[SIZED[2]]}
            )
    with SIZES.open("w", newline="") as f:
        w = csv.DictWriter(f, ["design", "pr", "commit", "design_lines", "ledger", "synopses"])
        w.writeheader()
        w.writerows(out)
    print(f"{len(out)} rows written to {SIZES.name}")


def report() -> None:
    model = _model()
    rows = list(csv.DictReader(TURNS.open()))
    size = defaultdict(int)
    for r in csv.DictReader(SIZES.open()):
        size[r["design"]] += int(r["design_lines"]) + int(r["ledger"]) + int(r["synopses"])
    print(
        "| design | design PRs | lines added | designer turns | reviewer turns | designer $ | reviewers $ | $ |"
        " $ per 100 lines |"
    )
    print("|---|---|---|---|---|---|---|---|---|")
    per100 = []
    tot = defaultdict(float)
    for td, prs in DESIGNS.items():
        mine = [r for r in rows if r["design"] == td]
        main = [r for r in mine if r["phase"] not in ("reviewer", "report")]
        rev = [r for r in mine if r["phase"] == "reviewer"]
        cm, cr = sum(model.cost(r) for r in main), sum(model.cost(r) for r in rev)
        lines = size[td]
        p = 100 * (cm + cr) / lines if lines else 0.0
        if mine:
            per100.append(p)
        for k, v in (("lines", lines), ("main", len(main)), ("rev", len(rev)), ("cm", cm), ("cr", cr)):
            tot[k] += v
        cost = f"{cm:.2f} | {cr:.2f} | {cm + cr:.2f} | {p:.2f}" if mine else "- | - | - | -"
        print(f"| {td} | {', '.join(f'#{n}' for n, _, _ in prs)} | {lines} | {len(main)} | {len(rev)} | {cost} |")
    c = tot["cm"] + tot["cr"]
    print(
        f"| all ten | | {int(tot['lines'])} | {int(tot['main'])} | {int(tot['rev'])} | {tot['cm']:.2f} |"
        f" {tot['cr']:.2f} | {c:.2f} | {100 * c / tot['lines']:.2f} |"
    )
    print(f"\nmedian $ per 100 lines over the {len(per100)} costed: {statistics.median(per100):.2f}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["select"]:
        select(Path(sys.argv[2]))
    elif sys.argv[1:] == ["sizes"]:
        sizes()
    else:
        report()
