"""Check a flow file (TD-1954 trial). Usage: flowcheck.py <flow.yml>. Prints OK, or each problem."""

import sys

import yaml

OUT = {
    "design": ["pull-request-open", "not-needed"],
    "build": ["pull-request-open", "branch-pushed", "design-needs-changing", "not-needed"],
    "review": ["ship", "changes-wanted"],
    "fact-check": ["ship", "changes-wanted"],
    "merge": ["merged", "cannot-merge"],
}
FIXED = ("next-action", "person", "done")
WRITES, READS = {"design", "build"}, {"review", "fact-check"}


def slug(name):
    return str(name).strip().lower().replace(" ", "-")


def check(doc):
    bad, info = [], []
    if not isinstance(doc, dict) or not isinstance(doc.get("stages"), list) or not doc["stages"]:
        return ["the file needs a `stages:` list with at least one stage"], info
    for k in doc:
        if k not in ("format", "name", "stages"):
            bad.append(f"unknown key at the top: {k}")
    if doc.get("format") != 2:
        bad.append("`format: 2` is required")
    stages, takes = {}, {"design-first": [], "other": []}
    for i, st in enumerate(doc["stages"], 1):
        if not isinstance(st, dict) or not st.get("name"):
            bad.append(f"stage {i} has no name")
            continue
        for k in st:
            if k not in ("name", "model", "takes", "actions", "next"):
                bad.append(f"{st['name']}: unknown key `{k}`")
        key = slug(st["name"])
        if key in stages or key in FIXED:
            bad.append(f"{st['name']}: the name is already used, or is a reserved word")
            continue
        acts = []
        for a in st.get("actions") or []:
            if isinstance(a, dict) and list(a.items()) == [("review", "protected-paths")]:
                acts.append("review")
            elif isinstance(a, str) and a in OUT:
                acts.append(a)
            else:
                bad.append(f"{st['name']}: unknown action {a!r}")
        if not acts:
            bad.append(f"{st['name']}: a stage needs at least one action")
        if not st.get("model"):
            bad.append(f"{st['name']}: a stage needs a model")
        if set(acts) & WRITES and set(acts) & READS:
            bad.append(f"{st['name']}: review or fact-check cannot share a stage with design or build (rule 5)")
        if "merge" in acts and set(acts) & WRITES and acts.index("merge") < max(acts.index(a) for a in acts if a in WRITES):
            bad.append(f"{st['name']}: merge comes before the action that opens the pull request (rule 6)")
        t = st.get("takes")
        if t not in (None, "design-first", "other", "any"):
            bad.append(f"{st['name']}: takes must be design-first, other or any")
        for kind in takes:
            if t in (kind, "any"):
                takes[kind].append(st["name"])
        stages[key] = {"name": st["name"], "acts": acts, "next": st.get("next") or {}, "edges": []}
    for kind, who in takes.items():
        if len(who) != 1:
            bad.append(f"new `{kind}` entries need exactly one stage that takes them; found {len(who)} (rule 7)")
    for key, st in stages.items():
        legal = {o for a in st["acts"] for o in OUT[a]} | {"stuck"}
        for o in st["next"]:
            if o not in legal:
                bad.append(f"{st['name']}: `{o}` is not an outcome of this stage's actions (rule 2)")
        for o in sorted(legal):
            v = st["next"].get(o, "done" if o == "merged" else "person")
            lim = None
            if isinstance(v, dict):
                if set(v) != {"to", "limit"} or not isinstance(v["limit"], int) or v["limit"] < 1:
                    bad.append(f"{st['name']}: `{o}` must be a destination or {{to: …, limit: n}}")
                    continue
                v, lim = v["to"], v["limit"]
            v = slug(v) if v not in FIXED else v
            if v == "next-action":
                owner = next(a for a in st["acts"] if o in OUT.get(a, [])) if o != "stuck" else None
                if owner is None or st["acts"].index(owner) == len(st["acts"]) - 1:
                    bad.append(f"{st['name']}: `{o}: next-action` has no following action in this stage (rule 1)")
                continue
            if v == "person":
                info.append(f"{st['name']}: {o} goes to the person" + ("" if o in st["next"] else " (not listed)"))
            elif v != "done" and v not in stages:
                bad.append(f"{st['name']}: `{o}` goes to `{v}`, which is not a stage (rule 1)")
            elif v != "done":
                st["edges"].append((o, v, lim))
                if o == "branch-pushed" and "build" not in stages[v]["acts"]:
                    bad.append(f"{st['name']}: branch-pushed must go to a stage that has build")
    # rule 3: no loop made only of moves without a limit
    free = {k: [v for _, v, lim in st["edges"] if lim is None] for k, st in stages.items()}
    for start in stages:
        seen, todo = set(), list(free[start])
        while todo:
            k = todo.pop()
            if k == start:
                bad.append(f"a loop through {stages[start]['name']} has no limit on any of its moves (rule 3)")
                break
            if k not in seen:
                seen.add(k)
                todo += free[k]
    # rule 4: from every stage that opens a pull request, a merge is reachable or it goes to the person
    def reach(k):
        seen, todo = {k}, [k]
        while todo:
            for _, v, _ in stages[todo.pop()]["edges"]:
                if v not in seen:
                    seen.add(v)
                    todo.append(v)
        return seen

    for key, st in stages.items():
        if set(st["acts"]) & WRITES and "pull-request-open" in {o for o, _, _ in st["edges"]} | set():
            if not any("merge" in stages[k]["acts"] for k in reach(key)):
                bad.append(f"{st['name']}: its pull request can never reach a merge (rule 4)")
    entered = {v for st in stages.values() for _, v, _ in st["edges"]} | {slug(n) for who in takes.values() for n in who}
    for key, st in stages.items():
        if key not in entered:
            info.append(f"{st['name']}: nothing can reach this stage")
    return bad, info


if __name__ == "__main__":
    try:
        doc = yaml.safe_load(open(sys.argv[1]))
    except Exception as e:  # noqa: BLE001
        print(f"PROBLEM: the file is not valid YAML: {e}")
        sys.exit(1)
    bad, info = check(doc)
    for b in dict.fromkeys(bad):
        print("PROBLEM:", b)
    for i in info:
        print("info:", i)
    print("OK" if not bad else f"{len(dict.fromkeys(bad))} problem(s)")
    sys.exit(1 if bad else 0)
