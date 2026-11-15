"""The replays section of the trial report (TD-1774): marks by situation, the costs and the three lines.

Run from the repo root: python docs/decisions/2026-11-12-design-trial/replays/lines.py
"""

import collections
import csv
import sys
from pathlib import Path

sys.path.insert(0, "docs/decisions/2026-11-12-design-cost-model")
import tables  # noqa: E402

D = Path("docs/decisions/2026-11-12-design-trial")
SCORED = ("TD-1557", "TD-1569")
HARD = {"interaction", "concurrency", "when", "ends", "who", "failure", "restart"}


def read(p: Path) -> list[dict]:
    return list(csv.DictReader(p.read_text().splitlines()))


def bad(m: dict) -> bool:
    return m["mark"] in ("silent", "wrongly-handled")


def na(m: dict) -> bool:
    return m["mark"] == "not-applicable"


def design(td: str) -> list[tuple[dict, dict, dict]]:
    """Each key row of `td` with the replay's mark and the original's."""
    key = {r["id"]: r for r in read(D / "keys" / f"{td}.csv")}
    marks: dict[str, dict] = collections.defaultdict(dict)
    for r in read(D / "replays" / td / "marks.csv"):
        marks[r["id"]][r["design"]] = r
    rows = [(k, marks[i]["replay"], marks[i]["original"]) for i, k in key.items()]
    print(f"== {td}: key {len(key)} rows")
    by: dict[tuple[str, str], collections.Counter] = collections.defaultdict(collections.Counter)
    for k, rep, orig in rows:
        for who, m in (("replay", rep), ("original", orig)):
            by[(k["situation"], who)][m["mark"] + ("·" + m["na"] if m["na"] != "-" else "")] += 1
    for s in sorted({s for s, _ in by}):
        print(f"  {s:12} replay {dict(by[(s, 'replay')])}  original {dict(by[(s, 'original')])}")
    rt = list(read(D / "replays" / td / "turns.csv"))
    ot = [r for r in read(D / "originals" / "turns.csv") if r["design"] == td]
    for who, turns in (("replay", rt), ("original", ot)):
        cost: dict[str, float] = collections.defaultdict(float)
        for r in turns:
            cost[r["model"] or "-"] += tables.cost(r)
        print(f"  cost {who} ${sum(cost.values()):.2f}: " + ", ".join(f"{m} ${c:.2f}" for m, c in sorted(cost.items())))
    return rows


def line(name: str, rows: list[tuple[dict, dict, dict]], whole_key: bool) -> None:
    """The replays' share less the originals' over the same rows."""
    if whole_key:
        # not applicable counts as not handled, but for a person's row and a false claim the result does not make

        def count(pick: int) -> tuple[int, int]:
            n = b = 0
            for row in rows:
                k, m = row[0], row[pick]
                if na(m) and (m["na"] == "person" or k["kind"] == "false-claim"):
                    continue
                n += 1
                b += bad(m) or na(m)
            return b, n

        (rb, rn), (ob, on) = count(1), count(2)
    else:
        same = [(r, o) for _, r, o in rows if not na(r) and not na(o)]
        rn = on = len(same)
        rb, ob = sum(bad(r) for r, _ in same), sum(bad(o) for _, o in same)
    print(
        f"{name}: replay {rb}/{rn} = {rb / rn:.3f}; original {ob}/{on} = {ob / on:.3f}; "
        f"difference {rb / rn - ob / on:+.3f}"
    )


def main() -> None:
    pool = [row for td in SCORED for row in design(td)]
    print("== lines, " + " and ".join(SCORED) + " pooled")
    line("scored rows (limit 0.100)", pool, False)
    line("scored rows, hard situations (limit 0.100)", [p for p in pool if p[0]["situation"] in HARD], False)
    line("whole key (limit 0.125)", pool, True)


if __name__ == "__main__":
    main()
