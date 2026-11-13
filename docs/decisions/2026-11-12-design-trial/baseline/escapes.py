"""The escape lister (TD-1775, design §4.9c *The baseline*, *escapes*): for one design, the candidates the trace
labeller reads with `../trace-prompt.md` (TD-1776, at the reading).

    python escapes.py TD-<n> [--ref <commit>] [--json]

- **The design's window** opens at the merge of its first design PR (the first in its entry's `Design PR:`, the
  PR that files its builds) and runs 28 days.
- **Its builds** are the entries whose `Part of:` names the design and whose `Kind:` is `build` (or a `live-check`
  it became), read from the ledger at `--ref` (default `origin/main`), active and archived. A **build PR** is a
  merged PR whose title leads with the build's id, merged in the design's window; a build with none there is
  outside the half.
- **Its review findings** are the numbered items (`1.`, `2.` …) of each review-evidence comment on a build PR: a
  comment with a `cadence-review:` line whose verdict is not `FIXED` (a `FIXED` comment answers findings, it raises
  none).
- **Its fix PRs** are the merged PRs, merged after the build's first build PR and within 14 days of its last, whose
  title does not lead with the build's id and whose title or body holds the build's or the design's id.

Each list is read from the forge by `gh`; nothing is written.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timedelta

WINDOW = timedelta(days=28)
FIX_WINDOW = timedelta(days=14)


def sh(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout


def when(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def entry(td: str, ref: str) -> str:
    for path in (f"docs/ledger/{td}.md", f"docs/ledger/archive/{td}.md"):
        try:
            return sh("git", "show", f"{ref}:{path}")
        except subprocess.CalledProcessError:
            continue
    raise SystemExit(f"{td}: no entry at {ref}")


def field(text: str, name: str) -> str:
    m = re.search(rf"^\*\*{re.escape(name)}:\*\*\s*(.*)$", text, re.M)
    return m.group(1).strip() if m else ""


def builds(design: str, ref: str) -> list[str]:
    out = []
    for path in sh("git", "ls-tree", "-r", "--name-only", ref, "docs/ledger/").split():
        m = re.fullmatch(r"docs/ledger/(?:archive/)?(TD-\d+)\.md", path)
        if not m:
            continue
        text = sh("git", "show", f"{ref}:{path}")
        part = re.findall(r"TD-\d+", field(text, "Part of"))
        kind = field(text, "Kind")
        if design in part and (kind == "build" or kind.startswith("live-check")):
            out.append(m.group(1))
    return sorted(out, key=lambda t: int(t[3:]))


def prs(search: str) -> list[dict]:
    text = sh(
        "gh", "pr", "list", "--state", "merged", "--limit", "300", "--search", search,
        "--json", "number,title,body,mergedAt",
    )  # fmt: skip
    return json.loads(text)


def holds(text: str, td: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(td)}(?!\d)", text or "") is not None


def leads(title: str, td: str) -> bool:
    return re.match(rf"{re.escape(td)}(?!\d)", title) is not None


def findings(pr: int) -> list[str]:
    bodies = json.loads(sh("gh", "pr", "view", str(pr), "--json", "comments"))["comments"]
    out = []
    for c in bodies:
        body = c["body"]
        m = re.search(r"^cadence-review:\s*(\w+)", body, re.M)
        if not m or m.group(1) == "FIXED":
            continue
        out += [ln.strip() for ln in body.splitlines() if re.match(r"\s*\d+\.\s", ln)]
    return out


def escapes(design: str, ref: str) -> dict:
    first = re.findall(r"#(\d+)", field(entry(design, ref), "Design PR"))
    if not first:
        raise SystemExit(f"{design}: no Design PR line")
    opened = when(json.loads(sh("gh", "pr", "view", first[0], "--json", "mergedAt"))["mergedAt"])
    result = {
        "design": design,
        "first_design_pr": int(first[0]),
        "window": [opened.isoformat(), (opened + WINDOW).isoformat()],
    }
    result["builds"] = []
    for b in builds(design, ref):
        mine = sorted(
            (
                p
                for p in prs(f"{b} in:title")
                if leads(p["title"], b) and opened <= when(p["mergedAt"]) <= opened + WINDOW
            ),
            key=lambda p: p["mergedAt"],
        )
        row = {"build": b, "prs": [], "fixes": []}
        if mine:
            lo, hi = when(mine[0]["mergedAt"]), when(mine[-1]["mergedAt"]) + FIX_WINDOW
            for p in mine:
                row["prs"].append(
                    {"pr": p["number"], "title": p["title"], "merged": p["mergedAt"], "findings": findings(p["number"])}
                )
            seen = set()
            for td in (b, design):
                for p in prs(td):
                    t = when(p["mergedAt"])
                    if p["number"] in seen or leads(p["title"], b) or not lo < t <= hi:
                        continue
                    if holds(p["title"], td) or holds(p["body"], td):
                        seen.add(p["number"])
                        row["fixes"].append({"pr": p["number"], "title": p["title"], "merged": p["mergedAt"]})
            row["fixes"].sort(key=lambda p: p["merged"])
        result["builds"].append(row)
    return result


def show(r: dict) -> None:
    print(
        f"{r['design']}: window {r['window'][0][:10]} to {r['window'][1][:10]}"
        f" (first design PR #{r['first_design_pr']})"
    )
    for b in r["builds"]:
        if not b["prs"]:
            print(f"\n{b['build']}: no build PR merged in the window")
            continue
        print(f"\n{b['build']}:")
        for p in b["prs"]:
            print(f"  build #{p['pr']} {p['merged'][:10]} {p['title'][:90]}")
            for f in p["findings"]:
                print(f"    finding: {f[:160]}")
        for p in b["fixes"]:
            print(f"  fix   #{p['pr']} {p['merged'][:10]} {p['title'][:90]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("design")
    ap.add_argument("--ref", default="origin/main")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = escapes(a.design, a.ref)
    print(json.dumps(r, indent=1)) if a.json else show(r)
