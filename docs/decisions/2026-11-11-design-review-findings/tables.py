#!/usr/bin/env python3
"""Rebuild the tables of docs/decisions/2026-11-11-design-review-findings.md.

Reads the review records (docs/reviews/TD-*.md) at a commit and the labels beside this file.

    python3 docs/decisions/2026-11-11-design-review-findings/tables.py [commit]

The commit defaults to the one the labels were made on. A later commit prints the same tables over
the findings that have a label; findings added since are counted as unlabelled and left out.
"""

import collections as C
import csv
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
COMMIT = sys.argv[1] if len(sys.argv) > 1 else "df866eeb8"
DEFERRABLE = {"wording", "naming", "xref", "test", "bookkeeping"}


def git(*args):
    return subprocess.run(["git", "-C", str(HERE), *args], capture_output=True, text=True, check=True).stdout


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def model_of(text):
    low = text.lower()
    return "fable" if "fable" in low else "sonnet" if "sonnet" in low else "?"


def read_records():
    """Every finding and every review of the records whose Source is `rounds`."""
    findings, reviews, designs = {}, [], 0
    names = git("ls-tree", "--name-only", "--full-tree", COMMIT, "docs/reviews/").split()
    for name in sorted(n for n in names if re.search(r"/TD-\d+\.md$", n)):
        text = git("show", f"{COMMIT}:{name}")
        if "Source:** backfill" in text:
            continue
        designs += 1
        td = pathlib.Path(name).stem
        by_review = {}
        for line in text.splitlines():
            c = cells(line)
            if re.match(r"\|\s*R\d+\s*\|", line) and len(c) >= 5:
                role = "fact-check" if c[2] == "fact-check" else "design"
                by_review[c[0]] = (role, model_of(c[3]))
                reviews.append((role, model_of(c[3]), int(re.sub(r"\D", "", c[4]) or 0)))
            if re.match(r"\|\s*F\d+\s*\|", line) and len(c) >= 7:
                role, model = by_review.get(c[2].split(",")[0].strip(), ("design", "?"))
                rnd = re.match(r"\d+", c[1])
                findings[f"{td}:{c[0]}"] = {
                    "td": td,
                    "n": int(c[0][1:]),
                    "round": min(int(rnd.group()), 5) if rnd else 0,
                    "role": role,
                    "model": model,
                    "text": " ".join([c[3], *c[4:-2], c[-1]]),
                    "label": c[-2] if c[-2] in ("minor", "build-changing") else "other",
                }
    return findings, reviews, designs


def table(title, rows, cols, row_of, col_of):
    counts = C.defaultdict(C.Counter)
    for fid in rows:
        counts[row_of(fid)][col_of(fid)] += 1
    print(f"\n{title}\n| | " + " | ".join(str(c) for c in cols) + " | all |\n|---" + "|---" * (len(cols) + 1) + "|")
    for r in sorted(counts, key=lambda r: -sum(counts[r].values())):
        total = sum(counts[r].values())
        print(f"| {r} | " + " | ".join(str(counts[r][c]) for c in cols) + f" | {total} |")


def main():
    findings, reviews, designs = read_records()
    with open(HERE / "labels.csv", newline="") as f:
        lab = {r["id"]: r for r in csv.DictReader(f)}
    ids = [i for i in findings if i in lab]
    print(f"records at {COMMIT}: {designs} designs, {len(reviews)} reviews, {len(findings)} findings, {len(ids)} labelled")

    group = lambda i: "unsure" if lab[i]["kind"] == "unsure" else "deferrable" if lab[i]["kind"] in DEFERRABLE else "substantive"  # noqa: E731
    kinds = ["build-changing", "minor", "other"]
    origins = ["fix-induced", "original", "unsure"]
    catches = ["builder", "mechanical", "design-only", "test", "none", "live", "pr-review", "unsure"]
    table("What was wrong, by the reviewer's own label", ids, kinds, lambda i: lab[i]["kind"], lambda i: findings[i]["label"])
    table("The reviewer's label against the narrow reading", ids, ["deferrable", "substantive", "unsure"], lambda i: findings[i]["label"], group)
    table("Where it would have been caught, by the reviewer's label", ids, kinds, lambda i: lab[i]["catch"], lambda i: findings[i]["label"])
    table("What was wrong against where it would have been caught", ids, catches, lambda i: lab[i]["kind"], lambda i: lab[i]["catch"])
    table("Origin by round (5 is round 5 and later)", ids, origins, lambda i: findings[i]["round"], lambda i: lab[i]["origin"])
    table("Subsystem by origin", ids, origins, lambda i: lab[i]["area"], lambda i: lab[i]["origin"])
    table("Subsystem by the reviewer's label", ids, kinds, lambda i: lab[i]["area"], lambda i: findings[i]["label"])

    # Follow-ups: a later finding of the same design that names this one by its id, followed transitively.
    kids = C.defaultdict(set)
    for i in ids:
        f = findings[i]
        for m in set(re.findall(r"F(\d+)", f["text"])):
            parent = f"{f['td']}:F{m}"
            if parent in findings and int(m) < f["n"]:
                kids[parent].add(i)

    def followers(i):
        seen, todo = set(), [i]
        while todo:
            for k in kids[todo.pop()]:
                if k not in seen:
                    seen.add(k)
                    todo.append(k)
        return seen

    print("\nFollow-ups by what was wrong\n| | findings | any follow-up | three or more | a build-changing follow-up |\n|---|---|---|---|---|")
    for kind in ["unspecified", "wrong-mechanism", "false-claim", "contradiction", "xref", "bookkeeping", "wording", "test"]:
        mine = [followers(i) for i in ids if lab[i]["kind"] == kind]
        n = len(mine) or 1
        some = sum(1 for d in mine if d)
        many = sum(1 for d in mine if len(d) >= 3)
        bc = sum(1 for d in mine if any(findings[k]["label"] == "build-changing" for k in d))
        print(f"| {kind} | {n} | {some} ({some / n:.0%}) | {many} ({many / n:.1%}) | {bc} ({bc / n:.1%}) |")

    print("\nReviewers by model and role\n| | reviews | tokens | findings | substantive | design-only or live | mechanical |\n|---|---|---|---|---|---|---|")
    for role, model in sorted(set((r, m) for r, m, _ in reviews)):
        mine = [i for i in ids if (findings[i]["role"], findings[i]["model"]) == (role, model)]
        n = sum(1 for r, m, _ in reviews if (r, m) == (role, model))
        tokens = sum(t for r, m, t in reviews if (r, m) == (role, model))
        print(
            f"| {model}, {role} | {n} | {tokens / 1e6:.1f}M | {len(mine)} | {sum(group(i) == 'substantive' for i in mine)}"
            f" | {sum(lab[i]['catch'] in ('design-only', 'live') for i in mine)} | {sum(lab[i]['catch'] == 'mechanical' for i in mine)} |"
        )

    # A sanity check a reader can repeat: the rows that say they reopen a finding should be fix-induced.
    cites = [i for i in ids if re.search(r"(reopens|corrects|refines|extends) F\d", findings[i]["text"])]
    agree = sum(lab[i]["origin"] == "fix-induced" for i in cites)
    print(f"\nrows that say they reopen, correct, refine or extend a finding: {len(cites)}, labelled fix-induced: {agree}")


if __name__ == "__main__":
    main()
