"""The baseline's findings, labelled (TD-1775, design §4.9c *The baseline*, *findings*).

    python labels.py inputs <dir>     # <dir>/TD-<n>.jsonl: each design's findings the analysis has not labelled
    python labels.py pinputs <dir>    # <dir>/p-in-TD-<n>.jsonl: the same rows with their merged labels, for the
                                      #   pattern pass (after `merge` has written labels.csv)
    python labels.py merge <dir>      # labels.csv and patterns.csv from <dir>/{a,b,c,p}-TD-<n>.jsonl
    python labels.py                  # prints the findings tables from labels.csv and patterns.csv

Every finding of the ten records, read at RECORDS (`git show`, never the work tree), as the analysis's `tables.py`
reads them (`../keys.py` `findings`). A finding the analysis labelled (its record was among the 41, read at
`df866eeb8`) keeps the analysis's labels as they are; every other is labelled by the analysis's `classify-prompt.md`
(two labellers on kind and origin, `a-` and `b-`, a third, `c-`, on the rows where they differ; catch and area the
first's) and `pattern-prompt.md` (one labeller, `p-`), as the replays' keys were.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ANALYSIS = HERE.parents[1] / "2026-11-11-design-review-findings"
RECORDS = "3d07c4efb0c14afc8492950b4c6ff39aed506a53"  # origin/main at the measurement, every record complete
DESIGNS = ("TD-1550", "TD-1573", "TD-1671", "TD-1650", "TD-1567", "TD-1543", "TD-1590", "TD-1568", "TD-1556", "TD-1577")
HARD = {"interaction", "concurrency", "when", "ends", "who", "failure", "restart"}
LABEL_FIELDS = ["id", "kind", "origin", "catch", "area"]
PATTERN_FIELDS = ["id", "case", "q", "fact", "check", "fixfail"]


def _keys():
    spec = importlib.util.spec_from_file_location("trial_keys", HERE.parent / "keys.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


K = _keys()


def analysis() -> tuple[dict, dict]:
    return (
        {r["id"]: r for r in K.read_csv(ANALYSIS / "labels.csv")},
        {r["id"]: r for r in K.read_csv(ANALYSIS / "patterns.csv")},
    )


def findings(td: str) -> list[dict]:
    return K.findings(td, RECORDS)


def _dump(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def inputs(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    labelled, _ = analysis()
    for td in DESIGNS:
        rows = [f for f in findings(td) if f["id"] not in labelled]
        if rows:
            _dump(out / f"{td}.jsonl", rows)
        print(f"{td}: {len(rows)} to label")


def pinputs(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    labelled, _ = analysis()
    mine = {r["id"]: r for r in K.read_csv(HERE / "labels.csv")}
    for td in DESIGNS:
        rows = [f | {k: mine[f["id"]][k] for k in LABEL_FIELDS[1:]} for f in findings(td) if f["id"] not in labelled]
        if rows:
            _dump(out / f"p-in-{td}.jsonl", rows)


def merge(d: Path) -> None:
    """labels.csv: the analysis's labels where it has them; else kind and origin where the two classify labellers
    agree, else the third's, catch and area the first's. patterns.csv: the analysis's, else the pattern labeller's.
    The pattern files may be absent at the first merge (the pattern pass reads the merged labels)."""
    have_l, have_p = analysis()
    labels, patterns, agree, missing_p = [], [], Counter(), 0
    for td in DESIGNS:
        rows = findings(td)
        if all(f["id"] in have_l for f in rows):
            a = b = c = p = {}
        else:
            a = {r["id"]: r for r in K.jsonl(d / f"a-{td}.jsonl")}
            b = {r["id"]: r for r in K.jsonl(d / f"b-{td}.jsonl")}
            cp, pp = d / f"c-{td}.jsonl", d / f"p-{td}.jsonl"
            c = {r["id"]: r for r in K.jsonl(cp)} if cp.exists() else {}
            p = {r["id"]: r for r in K.jsonl(pp)} if pp.exists() else {}
        for f in rows:
            i = f["id"]
            if i in have_l:
                labels.append({k: have_l[i][k] for k in LABEL_FIELDS})
                patterns.append({k: have_p[i][k] for k in PATTERN_FIELDS})
                continue
            row = {"id": i, "catch": a[i]["catch"], "area": a[i]["area"]}
            for k in ("kind", "origin"):
                same = a[i][k] == b[i][k]
                agree[(td, k, same)] += 1
                if same:
                    row[k] = a[i][k]
                elif i in c:
                    row[k] = c[i][k]
                else:
                    raise SystemExit(f"{i}: the labellers differ on {k} and no third reading")
            labels.append(row)
            if i in p:
                patterns.append({k: p[i][k] for k in PATTERN_FIELDS})
            else:
                missing_p += 1
    K.write_csv(HERE / "labels.csv", LABEL_FIELDS, labels)
    K.write_csv(HERE / "patterns.csv", PATTERN_FIELDS, patterns)
    for td in DESIGNS:
        for k in ("kind", "origin"):
            n_same, n_diff = agree[(td, k, True)], agree[(td, k, False)]
            if n_same + n_diff:
                print(f"{td} {k}: the two agree on {n_same} of {n_same + n_diff}")
    if missing_p:
        print(f"{missing_p} rows have no pattern label yet")


def thirds(d: Path) -> None:
    """<d>/c-in-TD-<n>.jsonl: the rows on which the two classify labellers differ on kind or origin."""
    for td in DESIGNS:
        ap = d / f"a-{td}.jsonl"
        if not ap.exists():
            continue
        a = {r["id"]: r for r in K.jsonl(ap)}
        b = {r["id"]: r for r in K.jsonl(d / f"b-{td}.jsonl")}
        rows = [
            f
            for f in findings(td)
            if f["id"] in a
            and (a[f["id"]]["kind"] != b[f["id"]]["kind"] or a[f["id"]]["origin"] != b[f["id"]]["origin"])
        ]
        if rows:
            _dump(d / f"c-in-{td}.jsonl", rows)
        print(f"{td}: {len(rows)} for the third")


def report() -> None:
    labels = {r["id"]: r for r in K.read_csv(HERE / "labels.csv")}
    patterns = {r["id"]: r for r in K.read_csv(HERE / "patterns.csv")}
    have_l, _ = analysis()
    print("| design | rounds | findings | the analysis's | per round | mechanical | fix-induced | hard after round 1 |")
    print("|---|---|---|---|---|---|---|---|")
    tot = Counter()
    for td in DESIGNS:
        rows = findings(td)
        rounds = max(int(f["round"]) for f in rows)
        n = len(rows)
        mech = sum(labels[f["id"]]["catch"] == "mechanical" for f in rows)
        fix = sum(labels[f["id"]]["origin"] == "fix-induced" for f in rows)
        hard = sum(patterns[f["id"]]["case"] in HARD and int(f["round"]) > 1 for f in rows)
        old = sum(f["id"] in have_l for f in rows)
        for k, v in (("rounds", rounds), ("n", n), ("old", old), ("mech", mech), ("fix", fix), ("hard", hard)):
            tot[k] += v
        print(
            f"| {td} | {rounds} | {n} | {old} | {n / rounds:.1f} | {100 * mech / n:.0f}% | {100 * fix / n:.0f}% |"
            f" {hard} |"
        )
    n = tot["n"]
    print(
        f"| all ten | {tot['rounds']} | {n} | {tot['old']} | {n / tot['rounds']:.1f} | {100 * tot['mech'] / n:.0f}% |"
        f" {100 * tot['fix'] / n:.0f}% | {tot['hard']} ({tot['hard'] / len(DESIGNS):.1f} a design) |"
    )


if __name__ == "__main__":
    cmd = sys.argv[1:2]
    if cmd == ["inputs"]:
        inputs(Path(sys.argv[2]))
    elif cmd == ["pinputs"]:
        pinputs(Path(sys.argv[2]))
    elif cmd == ["thirds"]:
        thirds(Path(sys.argv[2]))
    elif cmd == ["merge"]:
        merge(Path(sys.argv[2]))
    else:
        report()
