#!/usr/bin/env python3
"""The trial's answer keys (TD-1773, design §4.9c *The trial of the new shape*), rebuilt from the labels.

    python keys.py inputs <dir>      # the labellers' inputs: one JSON Lines file per labelled record
    python keys.py merge <dir>       # labels.csv and patterns.csv from the labellers' outputs in <dir>
    python keys.py asks <file>       # asks.csv from the asks reader's JSON Lines output
    python keys.py                   # keys/TD-<n>.csv from the labels, asks.csv and the records; prints the counts

The records are read at RECORDS (TD-1557 and TD-1569) and at the analysis's commit (TD-1470), never the work tree.
A key row is a finding of origin `original`, kind `unspecified`, `wrong-mechanism`, `contradiction` or `false-claim`,
and an outcome that does not start `rejected`; TD-1470's from rounds 1 to 8 only.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ANALYSIS = HERE.parent / "2026-11-11-design-review-findings"
RECORDS = "d798a53d1b64dbfd0139ab6735dbb29eae2e9440"  # TD-1557's and TD-1569's records, complete
ANALYSIS_COMMIT = "df866eeb8"  # the analysis's labels were made on the records here
LABELLED = ("TD-1557", "TD-1569")
KEYS = {"TD-1557": RECORDS, "TD-1569": RECORDS, "TD-1470": ANALYSIS_COMMIT}
MAX_ROUND = {"TD-1470": 8}
KEY_KINDS = {"unspecified", "wrong-mechanism", "contradiction", "false-claim"}
KEY_FIELDS = ["id", "round", "topic", "what", "class", "outcome", "kind", "situation", "q", "asks", "person"]


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(HERE), *args], capture_output=True, text=True, check=True).stdout


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def model_of(text: str) -> str:
    low = text.lower()
    return "fable" if "fable" in low else "sonnet" if "sonnet" in low else "?"


def findings(td: str, commit: str) -> list[dict]:
    """A record's findings in order, read as the analysis's tables.py reads them (a `|` inside a cell rejoined)."""
    text = git("show", f"{commit}:docs/reviews/{td}.md")
    by_review, out = {}, []
    for line in text.splitlines():
        c = cells(line)
        if re.match(r"\|\s*R\d+\s*\|", line) and len(c) >= 5:
            by_review[c[0]] = ("fact-check" if c[2] == "fact-check" else "design", model_of(c[3]))
        if re.match(r"\|\s*F\d+\s*\|", line) and len(c) >= 7:
            role, model = by_review.get(c[2].split(",")[0].strip(), ("design", "?"))
            out.append(
                {
                    "id": f"{td}:{c[0]}",
                    "round": c[1],
                    "by": c[2],
                    "role": role,
                    "model": model,
                    "topic": c[3],
                    "finding": " | ".join(c[4:-2]),
                    "label": c[-2],
                    "status": c[-1],
                }
            )
    return out


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def jsonl(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def inputs(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for td in LABELLED:
        rows = findings(td, RECORDS)
        (out / f"{td}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        print(f"{td}: {len(rows)} findings")


def merge(d: Path) -> None:
    """labels.csv: kind and origin where the two classify labellers agree, else the third's; catch and area the
    first's. patterns.csv: the pattern labeller's. Each from `<dir>/{a,b,c,p}-TD-<n>.jsonl`."""
    labels, patterns, agree = [], [], Counter()
    for td in LABELLED:
        a = {r["id"]: r for r in jsonl(d / f"a-{td}.jsonl")}
        b = {r["id"]: r for r in jsonl(d / f"b-{td}.jsonl")}
        third_path = d / f"c-{td}.jsonl"
        c = {r["id"]: r for r in jsonl(third_path)} if third_path.exists() else {}
        p = {r["id"]: r for r in jsonl(d / f"p-{td}.jsonl")}
        for f in findings(td, RECORDS):
            i = f["id"]
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
            patterns.append({k: p[i][k] for k in ("id", "case", "q", "fact", "check", "fixfail")})
    write_csv(HERE / "labels.csv", ["id", "kind", "origin", "catch", "area"], labels)
    write_csv(HERE / "patterns.csv", ["id", "case", "q", "fact", "check", "fixfail"], patterns)
    for td in LABELLED:
        for k in ("kind", "origin"):
            n_same, n_diff = agree[(td, k, True)], agree[(td, k, False)]
            print(f"{td} {k}: the two agree on {n_same} of {n_same + n_diff}")


def asks(path: Path) -> None:
    """asks.csv from the reader's output, checked against the keys' rows: one row each, in the keys' order."""
    got = jsonl(path)
    want = [r["id"] for td in KEYS for r in key_rows(td)]
    if [r["id"] for r in got] != want:
        raise SystemExit(f"{path}: its ids are not the keys' rows in order")
    if any(r["person"] not in ("yes", "no") or not r["asks"].strip() for r in got):
        raise SystemExit(f"{path}: an empty asks or a person not yes or no")
    write_csv(HERE / "asks.csv", ["id", "asks", "person"], got)
    print(f"asks.csv: {len(got)} rows, person yes {sum(r['person'] == 'yes' for r in got)}")


def key_rows(td: str) -> list[dict]:
    src = HERE if td in LABELLED else ANALYSIS
    lab = {r["id"]: r for r in read_csv(src / "labels.csv")}
    pat = {r["id"]: r for r in read_csv(src / "patterns.csv")}
    out = []
    for f in findings(td, KEYS[td]):
        i, rnd = f["id"], re.match(r"\d+", f["round"])
        if td in MAX_ROUND and (not rnd or int(rnd.group()) > MAX_ROUND[td]):
            continue
        lb, pt = lab.get(i), pat.get(i, {})
        if not lb or lb["origin"] != "original" or lb["kind"] not in KEY_KINDS:
            continue
        if f["status"].lower().startswith("rejected"):
            continue
        out.append(
            {
                "id": i,
                "round": f["round"],
                "topic": f["topic"],
                "what": f["finding"],
                "class": f["label"],
                "outcome": f["status"],
                "kind": lb["kind"],
                "situation": pt.get("case", "-") or "-",
                "q": pt.get("q", "-") or "-",
            }
        )
    return out


def build() -> None:
    asks_path = HERE / "asks.csv"
    asks = {r["id"]: r for r in read_csv(asks_path)} if asks_path.exists() else {}
    for td in KEYS:
        rows = key_rows(td)
        missing = [r["id"] for r in rows if r["id"] not in asks]
        for r in rows:
            r["asks"] = asks.get(r["id"], {}).get("asks", "")
            r["person"] = asks.get(r["id"], {}).get("person", "")
        write_csv(HERE / "keys" / f"{td}.csv", KEY_FIELDS, rows)
        by = Counter(r["situation"] for r in rows)
        counts = " · ".join(f"{s} {n}" for s, n in sorted(by.items(), key=lambda x: (-x[1], x[0])))
        print(f"{td}: {len(rows)} key rows · {counts}")
        if missing:
            more = " …" if len(missing) > 5 else ""
            print(f"  {len(missing)} without a row in asks.csv: {', '.join(missing[:5])}{more}")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "inputs":
        inputs(Path(sys.argv[2]))
    elif len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(Path(sys.argv[2]))
    elif len(sys.argv) > 2 and sys.argv[1] == "asks":
        asks(Path(sys.argv[2]))
    else:
        build()
