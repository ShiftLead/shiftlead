"""The replays' scoring kit (TD-1774, design §4.9c *The score*): blind inputs for the scorers, then their marks merged.

    python score.py inputs TD-<n> <run k> <out dir>   # <out>/<label>/{diff,files/,tree/} for the replay and the
                                                      #   original, labels drawn at random; <out>/key.csv; <out>/LABELS
    python score.py thirds <out dir>                  # <out>/<label>/third-in.jsonl: rows the two read differently
                                                      #   or either marked not-applicable · absent, with both marks
    python score.py merge TD-<n> <out dir>            # TD-<n>/marks.csv: each row's mark for the replay and the
                                                      #   original, the third's where it read the row

A scorer reads `<label>/diff`, `<label>/files/` and `<label>/tree/` (a plain export at the design's commit, with no
history, no `docs/reviews/` and no `REPLAY.md`) and `key.csv` (`id`, `kind`, `asks`, `person`, `what`), and writes
`<label>/<s>.jsonl` (`s` = `a`, `b`; the third `c`). LABELS, which says which label is the replay, is read by
`merge` alone and is never given to a scorer.

The replay is run k's result: the overlay commit to the `replay result (TD-1722)` commit. The original is the
replay's base (the commit `replay base` names) to the merge of the last design PR its key's rounds ran in, kept to
the files the design's PRs touched.
"""

from __future__ import annotations

import csv
import io
import json
import random
import re
import subprocess
import sys
import tarfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRIAL = HERE.parent
REPLAYS = Path.home() / "replays"
REPO = TRIAL.parents[2]
# The merge of the last design PR the key's rounds ran in, and every design PR of those rounds (README, keys).
ORIGINAL = {
    "TD-1557": ("d798a53d1b64dbfd0139ab6735dbb29eae2e9440", ["3511"]),
    "TD-1569": ("a6474184a6a2fef2100b186421dafac5011f7f8f", ["3465"]),
    "TD-1470": ("365683cb", ["3107", "3152", "3189", "3226", "3246"]),
}
LEFT_OUT = ("docs/reviews/", "REPLAY.md")
MARKS = {"handled", "silent", "wrongly-handled", "not-applicable"}


def git(repo: Path, *args: str, binary: bool = False):
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True)
    return out.stdout if binary else out.stdout.decode()


def kept(path: str) -> bool:
    return not any(path == p or path.startswith(p) for p in LEFT_OUT)


def export(repo: Path, commit: str, dest: Path) -> None:
    dest.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(git(repo, "archive", commit, binary=True))) as tar:
        tar.extractall(dest, members=[m for m in tar.getmembers() if kept(m.name)], filter="tar")


def side(repo: Path, base: str, head: str, paths: list[str], dest: Path) -> None:
    """One design's inputs: its diff, the whole text of the files it touches, and its tree."""
    paths = [p for p in paths if kept(p)]
    (dest / "files").mkdir(parents=True)
    (dest / "diff").write_text(git(repo, "diff", base, head, "--", *paths))
    for p in paths:
        try:
            text = git(repo, "show", f"{head}:{p}", binary=True)
        except subprocess.CalledProcessError:
            continue  # deleted at the head
        out = dest / "files" / p
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(text)
    export(repo, head, dest / "tree")


def inputs(td: str, k: int, out: Path) -> None:
    run = REPLAYS / f"{td}.{k}"
    subjects = git(run, "log", "--format=%H %s").splitlines()
    if not subjects[0].endswith("replay result (TD-1722)"):
        raise SystemExit(f"{run}: its last commit is not the replay's result")
    overlay = next(line.split()[0] for line in subjects if line.endswith("replay overlay (TD-1722)"))
    base_line = next(line for line in subjects if " replay base: " in line)
    base = re.search(r" at ([0-9a-f]{7,40}) ", base_line).group(1)
    merge, prs = ORIGINAL[td]
    touched_paths = sorted(
        {
            f["path"]
            for pr in prs
            for f in json.loads(subprocess.check_output(["gh", "pr", "view", pr, "--json", "files"]))["files"]
        }
    )
    labels = ["p", "q"]
    random.shuffle(labels)
    out.mkdir(parents=True)
    replay_paths = git(run, "diff", "--name-only", overlay, "HEAD").split()
    side(run, overlay, "HEAD", replay_paths, out / labels[0])
    side(REPO, base, merge, touched_paths, out / labels[1])
    (out / "LABELS").write_text(f"replay {labels[0]}\noriginal {labels[1]}\n")
    rows = list(csv.DictReader((TRIAL / "keys" / f"{td}.csv").open()))
    with (out / "key.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, ["id", "kind", "asks", "person", "what"], extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"{td}: {len(rows)} key rows; inputs under {out}")


def jsonl(path: Path) -> dict[str, dict]:
    return {r["id"]: r for r in map(json.loads, path.read_text().splitlines()) if r}


def labels(out: Path) -> dict[str, str]:
    return {line.split()[0]: line.split()[1] for line in (out / "LABELS").read_text().splitlines()}


def needs_third(a: dict, b: dict) -> bool:
    return (a["mark"], a["na"]) != (b["mark"], b["na"]) or "absent" in (a["na"], b["na"])


def thirds(out: Path) -> None:
    for lab in labels(out).values():
        a, b = jsonl(out / lab / "a.jsonl"), jsonl(out / lab / "b.jsonl")
        rows = [
            {
                "id": i,
                "first": {k: a[i][k] for k in ("mark", "na", "why")},
                "second": {k: b[i][k] for k in ("mark", "na", "why")},
            }
            for i in a
            if needs_third(a[i], b[i])
        ]
        (out / lab / "third-in.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        print(f"{lab}: {len(rows)} rows for the third")


def merge(td: str, out: Path) -> None:
    rows = []
    for who, lab in sorted(labels(out).items()):
        a, b = jsonl(out / lab / "a.jsonl"), jsonl(out / lab / "b.jsonl")
        cp = out / lab / "c.jsonl"
        c = jsonl(cp) if cp.exists() else {}
        for i in a:
            if needs_third(a[i], b[i]) and i not in c:
                raise SystemExit(f"{who} {i}: the two differ or one is absent, and the third has not read it")
            final = c.get(i) or a[i]
            if final["mark"] not in MARKS:
                raise SystemExit(f"{who} {i}: mark {final['mark']!r}")
            rows.append(
                {"design": who, "id": i, "mark": final["mark"], "na": final["na"], "by": "third" if i in c else "two"}
            )
    dest = HERE / td
    dest.mkdir(exist_ok=True)
    with (dest / "marks.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, ["design", "id", "mark", "na", "by"])
        w.writeheader()
        w.writerows(rows)
    for who in ("replay", "original"):
        print(who, dict(Counter(r["mark"] for r in rows if r["design"] == who)))


if __name__ == "__main__":
    cmd = sys.argv[1:2]
    if cmd == ["inputs"]:
        inputs(sys.argv[2], int(sys.argv[3]), Path(sys.argv[4]))
    elif cmd == ["thirds"]:
        thirds(Path(sys.argv[2]))
    elif cmd == ["merge"]:
        merge(sys.argv[2], Path(sys.argv[3]))
    else:
        print(__doc__)
