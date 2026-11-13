"""The design cost model's tables (TD-1764), from `turns.csv` beside this file.

    python tables.py select <all turns csv>   # writes turns.csv: the five designs' turns, phased
    python tables.py                          # prints every table of the document from turns.csv

`all turns csv` is `extract.py`'s output over the designer's transcript directory. Every number in the
document is printed by the second form, so a second reader re-derives them from turns.csv alone.
"""

from __future__ import annotations

import csv
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TURNS = HERE / "turns.csv"

# Each design's branches, from its merged PRs (`gh pr list --search "TD-n in:title"`); a bought round's
# branch belongs to the design it reviews (TD-1676, TD-1702, TD-1708 are TD-1543's rounds 9-11, TD-1454's
# branch TD-1434's round 5).
DESIGNS = {
    "TD-1436": {"rounds": 3, "branches": ["td1436-answer-latency"]},
    "TD-1650": {"rounds": 4, "branches": ["td1650-design"]},
    "TD-1443": {"rounds": 4, "branches": ["td-1443-design"]},
    "TD-1434": {"rounds": 5, "branches": ["td1434-seat-mode-flip", "td1434-round5"]},
    "TD-1543": {
        "rounds": 11,
        "branches": ["td1543-design-have-a-session-do-it", "td-1676-round9", "td1702-round10", "td1708-round11"],
    },
}
LAUNCH = {"designer-ao-1", "main", "HEAD", ""}  # the worktree's own branch: a session's start, before its branch

# `ao spend`'s default weights (`sessionorc.seats.WEIGHTS`, as_of 2026-10-17), $ per million tokens; the
# longest model prefix wins. Settings may override them; this home's settings.yml sets none.
WEIGHTS = {
    "claude-fable": {"input": 10, "output": 50, "cache_read": 0.25, "cache_write": 20},
    "claude-opus": {"input": 4, "output": 20, "cache_read": 0.2, "cache_write": 8},
    "claude-sonnet": {"input": 2, "output": 10, "cache_read": 0.2, "cache_write": 4},
    "claude-haiku": {"input": 0.1, "output": 0.5, "cache_read": 0.01, "cache_write": 0.2},
    "claude-opus-5": {"input": 5, "output": 25, "cache_read": 0.5, "cache_write": 10},
    "claude-opus-5-5": {"input": 4, "output": 20, "cache_read": 0.2, "cache_write": 8},
    "claude-opus-4": {"input": 5, "output": 25, "cache_read": 0.5, "cache_write": 10},
    "claude-sonnet-4": {"input": 3, "output": 15, "cache_read": 0.3, "cache_write": 6},
    "claude-haiku-4": {"input": 1, "output": 5, "cache_read": 0.1, "cache_write": 2},
}
KINDS = ("input", "cache_read", "cache_write", "output")
PHASES = ("drafting", "applying", "reviews", "bookkeeping", "other")

# A turn's tools that make it bookkeeping (the ledger, the board, the review record, the PR and its merge).
BOOK = (
    "ledger.py",
    "board_edit",
    "docs/reviews/",
    "Bash:gh ",
    "git commit",
    "git -C commit",
    "git push",
    "git -C push",
    "ao progress",
    "ao board",
    "check_cadence",
    "precheck",
    "forge.py",
    "ao td",
    "ao pr",
    "Bash:git add",
    "Bash:git -C add",
    "history.py",
    "docs/history/",
)
# Tools that are neither the design nor its bookkeeping: mail, the record, the board view.
OTHER = (
    "ao inbox",
    "ao doing",
    "ao status",
    "ao msg",
    "ao repo",
    "attention",
    "ao --skill",
    "session-start",
    "ScheduleWakeup",
    "ToolSearch",
)


def weight(model: str) -> dict[str, float]:
    best = max((k for k in WEIGHTS if model.startswith(k)), key=len, default="claude-opus")
    return WEIGHTS[best]


def cost(r: dict, model: str | None = None) -> float:
    w = weight(model or r["model"])
    return sum(int(r[k]) * w[k] for k in KINDS) / 1e6


def klass(call: str) -> str:
    """One tool call's class, the only trace of it `turns.csv` keeps (no command text): `agent` (a reviewer
    started), `book` (the ledger, the board, the review record, the PR), `mail` (mail and records), `edit`,
    or `work` (any other read, search or command)."""
    if call.startswith("Agent:"):
        return "agent"
    if any(m in call for m in BOOK):
        return "book"
    if any(m in call for m in OTHER):
        return "mail"
    if call.startswith(("Edit:", "Write:")):
        return "edit"
    return "work"


def phase_of(calls: str, mode: str) -> str:
    """A turn's phase from its calls' classes: a reviewer started is sending a review; a turn of bookkeeping
    and mail alone is bookkeeping where any call is bookkeeping, else other; any other turn is the design's
    mode at that moment — drafting before the first review is sent, applying once a report has come back
    since the last send, else sending and waiting on reviews."""
    parts = [c for c in calls.split(";") if c]
    if "agent" in parts:
        return "reviews"
    if parts and set(parts) <= {"book", "mail"}:
        return "bookkeeping" if "book" in parts else "other"
    return mode


def select(src: Path) -> None:
    rows = list(csv.DictReader(src.open()))
    by_session: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_session[r["session"]].append(r)
    out = []
    for td, spec in DESIGNS.items():
        branches = set(spec["branches"])
        sessions = sorted({r["session"] for r in rows if r["branch"] in branches and not r["side"]})
        picked: list[dict] = []
        windows = []
        for s in sessions:
            main = sorted((r for r in by_session[s] if not r["side"]), key=lambda r: r["ts"])
            idx = [i for i, r in enumerate(main) if r["branch"] in branches]
            first, last = idx[0], idx[-1]
            # the session's start on the launch branch, back to its last turn on another branch
            while first > 0 and main[first - 1]["branch"] in LAUNCH:
                first -= 1
            keep = [r for r in main[first : last + 1] if r["branch"] in branches or r["branch"] in LAUNCH]
            picked += keep
            windows.append((s, keep[0]["ts"], keep[-1]["ts"]))
        picked.sort(key=lambda r: r["ts"])
        mode = "drafting"
        for r in picked:
            r["calls"] = "report" if r["tools"] == "REPORT" else ";".join(klass(c) for c in r["tools"].split(";") if c)
            del r["tools"]
            if r["calls"] == "report":
                mode = "applying"
                r["phase"] = "report"
                continue
            ph = phase_of(r["calls"], mode)
            if ph == "reviews":
                mode = "reviews"
            r["phase"] = ph
        for r in picked:
            r["design"] = td
        out += picked
        # the reviewers this design's sessions started within its window (their own spend, apart)
        for s, t0, t1 in windows:
            subs = defaultdict(list)
            for r in by_session[s]:
                if r["side"]:
                    subs[r["side"]].append(r)
            for rs in subs.values():
                if t0 <= min(x["ts"] for x in rs) <= t1:
                    for x in rs:
                        y = {k: v for k, v in x.items() if k != "tools"}
                        out.append({**y, "design": td, "phase": "reviewer", "calls": ""})
    fields = ["design", "phase"] + [k for k in rows[0] if k != "tools"] + ["calls"]
    with TURNS.open("w", newline="") as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows(out)
    print(f"{len(out)} rows written to {TURNS.name}")


def tables() -> None:
    rows = list(csv.DictReader(TURNS.open()))
    turns = [r for r in rows if r["phase"] in PHASES]
    print("## Per design and phase (the designer's own turns)\n")
    print("| design | phase | turns | input | cache read | cache write | output | $ | share | median context |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    pooled: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    shares = {}
    for td in DESIGNS:
        mine = [r for r in turns if r["design"] == td]
        total = sum(cost(r) for r in mine)
        for ph in PHASES:
            rs = [r for r in mine if r["phase"] == ph]
            c = sum(cost(r) for r in rs)
            p = pooled[ph]
            p["turns"] += len(rs)
            p["$"] += c
            for k in KINDS:
                p[k] += sum(int(r[k]) for r in rs)
            med = int(statistics.median(int(r["context"]) for r in rs)) if rs else 0
            print(
                f"| {td} | {ph} | {len(rs)} | "
                + " | ".join(f"{sum(int(r[k]) for r in rs):,}" for k in KINDS)
                + f" | {c:.2f} | {c / total:.0%} | {med:,} |"
            )
        shares[td] = (sum(cost(r) for r in mine if r["phase"] == "applying") / total, total)
        print(f"| {td} | **all** | {len(mine)} | | | | | {total:.2f} | | |")
    print("\n## Pooled\n")
    grand = sum(p["$"] for p in pooled.values())
    print("| phase | turns | $ | share |")
    print("|---|---|---|---|")
    for ph in PHASES:
        print(f"| {ph} | {int(pooled[ph]['turns'])} | {pooled[ph]['$']:.2f} | {pooled[ph]['$'] / grand:.0%} |")
    print(f"| all | {sum(int(p['turns']) for p in pooled.values())} | {grand:.2f} | |")
    print("\n## Applying fixes, per design\n")
    print("| design | rounds | designer $ | applying share | reviewers $ | models |")
    print("|---|---|---|---|---|---|")
    for td, (share, total) in shares.items():
        rev = sum(cost(r) for r in rows if r["design"] == td and r["phase"] == "reviewer")
        models = sorted({r["model"] for r in turns if r["design"] == td and r["model"]})
        print(f"| {td} | {DESIGNS[td]['rounds']} | {total:.2f} | {share:.0%} | {rev:.2f} | {', '.join(models)} |")
    print("\n## The reviewers, by model (pooled)\n")
    print("| model | $ |")
    print("|---|---|")
    by_model: dict[str, float] = defaultdict(float)
    for r in rows:
        if r["phase"] == "reviewer":
            by_model[r["model"]] += cost(r)
    for m, c in sorted(by_model.items()):
        print(f"| {m} | {c:.2f} |")
    print(f"| all | {sum(by_model.values()):.2f} |")
    print("\n## By day (the designer's turns, UTC days)\n")
    print("| design | day | $ |")
    print("|---|---|---|")
    for td in DESIGNS:
        days: dict[str, float] = defaultdict(float)
        for r in turns:
            if r["design"] == td:
                days[r["ts"][:10]] += cost(r)
        for d, c in sorted(days.items()):
            print(f"| {td} | {d} | {c:.2f} |")
    estimates(turns)


def episodes(turns: list[dict]) -> dict[str, list[list[dict]]]:
    """Each design's applying turns, cut into runs: one run from a report to the next review sent."""
    out: dict[str, list[list[dict]]] = defaultdict(list)
    for td in DESIGNS:
        run: list[dict] = []
        for r in sorted((r for r in turns if r["design"] == td), key=lambda r: r["ts"]):
            if r["phase"] == "applying":
                run.append(r)
            elif r["phase"] == "reviews" and run:
                out[td].append(run)
                run = []
        if run:
            out[td].append(run)
    return out


# Step 4's assumptions (the document states them): a fresh Sonnet seat starts each fix run from a context of
# BASE tokens (its system prompt and tools, the design's sections and the review record), written once to the
# cache, and grows as the designer's context grew over that run; it takes as many turns and writes as much
# output. A question to Fable is a span, its findings and the paragraphs they cite (QUESTION tokens) and
# ANSWER tokens out; fresh, on top of a session's start (START tokens, written to the cache).
BASE = 60_000
START = 25_000
QUESTION = 12_000
ANSWER = 2_000


def sonnet_fresh(eps: dict[str, list[list[dict]]], base: int) -> float:
    son = WEIGHTS["claude-sonnet"]
    total = 0.0
    for runs in eps.values():
        for run in runs:
            c0 = int(run[0]["context"])
            total += base * son["cache_write"] / 1e6
            for r in run:
                total += (
                    (base + max(0, int(r["context"]) - c0)) * son["cache_read"] + int(r["output"]) * son["output"]
                ) / 1e6
    return total


def estimates(turns: list[dict]) -> None:
    print("\n## Step 4: the same fix turns on Sonnet from a fresh context\n")
    print("| design | fix runs | fix turns | as run $ | on Sonnet, fresh $ | ratio |")
    print("|---|---|---|---|---|---|")
    son = WEIGHTS["claude-sonnet"]
    tot_run = tot_son = 0.0
    for td, runs in episodes(turns).items():
        as_run = sum(cost(r) for run in runs for r in run)
        fresh = 0.0
        for run in runs:
            c0 = int(run[0]["context"])
            fresh += BASE * son["cache_write"] / 1e6
            for r in run:
                ctx = BASE + max(0, int(r["context"]) - c0)
                fresh += (ctx * son["cache_read"] + int(r["output"]) * son["output"]) / 1e6
        tot_run, tot_son = tot_run + as_run, tot_son + fresh
        n = sum(len(run) for run in runs)
        print(f"| {td} | {len(runs)} | {n} | {as_run:.2f} | {fresh:.2f} | {fresh / as_run:.2f} |")
    print(f"| pooled | | | {tot_run:.2f} | {tot_son:.2f} | {tot_son / tot_run:.2f} |")
    print("\nSensitivity, pooled, to the fresh context's size:\n")
    print("| BASE tokens | on Sonnet, fresh $ | ratio |")
    print("|---|---|---|")
    for base in (40_000, 60_000, 100_000, 150_000):
        f = sonnet_fresh(episodes(turns), base)
        print(f"| {base:,} | {f:.2f} | {f / tot_run:.2f} |")
    print("\n## Step 4: one question to Fable\n")
    fab = WEIGHTS["claude-fable"]
    fresh = ((START + QUESTION) * fab["cache_write"] + ANSWER * fab["output"]) / 1e6
    ctxs = [int(r["context"]) for r in turns if r["phase"] == "applying"]
    med = int(statistics.median(ctxs))
    in_session = ((med * fab["cache_read"]) + QUESTION * fab["cache_write"] + ANSWER * fab["output"]) / 1e6
    print("| where | context read | $ |")
    print("|---|---|---|")
    print(f"| a fresh Fable session | {START + QUESTION:,} written | {fresh:.2f} |")
    print(f"| the designer's own session, at its median applying context | {med:,} read | {in_session:.2f} |")


# TD-1721's pricing (design §4.9c *Who reviews a design's rounds*, *What the designer carries*): each reviewer
# subagent's spend by model, and the designer's spend had each design (or each round past a bound) started in a
# fresh run. A fresh run starts at START_RUN tokens, the median first turn of a design session in this sample;
# carrying less shrinks only a turn's cache read, and a run ended mid-design pays its reload as a cache write.
START_RUN = 60_000


def reviewers(rows: list[dict]) -> dict[str, list[float]]:
    agents: dict[tuple, list] = defaultdict(lambda: [0.0, ""])
    for r in rows:
        if r["phase"] == "reviewer":
            a = agents[(r["design"], r["side"])]
            a[0] += cost(r)
            a[1] = r["model"]
    out: dict[str, list[float]] = defaultdict(list)
    for c, model in agents.values():
        out[next((k for k in ("fable", "sonnet", "opus") if k in model), model)].append(c)
    return out


def fresh_runs(turns: list[dict], bound: int | None) -> float:
    w = WEIGHTS["claude-opus-5-5"]
    total = 0.0
    for td in DESIGNS:
        session, off = None, 0
        for r in sorted((r for r in turns if r["design"] == td), key=lambda r: r["ts"]):
            ctx = int(r["context"])
            if r["session"] != session:
                session, off = r["session"], max(0, ctx - START_RUN)
            if bound and ctx - off > bound:
                off = ctx - START_RUN
                total += START_RUN * w["cache_write"] / 1e6
            total += cost(r) - min(int(r["cache_read"]), off) * w["cache_read"] / 1e6
    return total


def td1721() -> None:
    rows = list(csv.DictReader(TURNS.open()))
    turns = [r for r in rows if r["phase"] in PHASES]
    print("## For TD-1721: one review, by model\n")
    print("| model | reviews | $ | mean $ | median $ |")
    print("|---|---|---|---|---|")
    for m, cs in sorted(reviewers(rows).items()):
        print(f"| {m} | {len(cs)} | {sum(cs):.2f} | {sum(cs) / len(cs):.2f} | {statistics.median(cs):.2f} |")
    as_run = sum(cost(r) for r in turns)
    print("\n## For TD-1721: the designer, from a fresh run\n")
    print("| the designer's runs | $ | ratio |")
    print("|---|---|---|")
    print(f"| as run | {as_run:.2f} | 1.00 |")
    for label, bound in (("a fresh run at each design's start", None), ("and again past 150k mid-design", 150_000)):
        f = fresh_runs(turns, bound)
        print(f"| {label} | {f:.2f} | {f / as_run:.2f} |")
    by_round()


def by_round() -> None:
    """Findings only a design review (or live use) would catch, for each review, by round and reviewer, over the
    findings analysis's 41 records at its commit, with its labels (rounds 5 and later together, as it counts)."""
    import importlib.util

    path = HERE.parent / "2026-11-11-design-review-findings" / "tables.py"
    spec = importlib.util.spec_from_file_location("findings", path)
    fa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fa)
    fa.COMMIT = "df866eeb8"
    findings, _, designs = fa.read_records()
    labels = {r["id"]: r["catch"] for r in csv.DictReader((path.parent / "labels.csv").open())}
    reviews: dict[tuple, int] = defaultdict(int)
    for name in fa.git("ls-tree", "--name-only", "--full-tree", fa.COMMIT, "docs/reviews/").split():
        if not re.search(r"/TD-\d+\.md$", name):
            continue
        text = fa.git("show", f"{fa.COMMIT}:{name}")
        if "Source:** backfill" in text:
            continue
        for line in text.splitlines():
            c = fa.cells(line)
            if re.match(r"\|\s*R\d+\s*\|", line) and len(c) >= 5 and c[2] != "fact-check":
                rnd = re.match(r"\d+", c[1])
                reviews[(min(int(rnd.group()), 5) if rnd else 0, fa.model_of(c[3]))] += 1
    found: dict[tuple, int] = defaultdict(int)
    for i, f in findings.items():
        if f["role"] == "design" and labels.get(i) in ("design-only", "live"):
            found[(f["round"], f["model"])] += 1
    print(f"\n## For TD-1721: design-only findings for each design review, by round ({designs} designs)\n")
    print("| round | Fable reviews | Fable, each | Sonnet reviews | Sonnet, each |")
    print("|---|---|---|---|---|")
    for rnd in range(1, 6):
        cells = []
        for m in ("fable", "sonnet"):
            n = reviews[(rnd, m)]
            cells += [str(n), f"{found[(rnd, m)] / n:.2f}" if n else "-"]
        print(f"| {rnd if rnd < 5 else '5 and later'} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "select":
        select(Path(sys.argv[2]))
    elif sys.argv[1:] == ["td1721"]:
        td1721()
    else:
        tables()
