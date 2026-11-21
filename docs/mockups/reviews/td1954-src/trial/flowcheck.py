"""Check a flow file (TD-1954 trial, second cut). Usage: flowcheck.py <flow.yml>. Prints OK, or each problem."""

import sys

import yaml

OUT = {
    "design": ["pull-request-open", "branch-pushed", "not-needed"],
    "build": ["pull-request-open", "branch-pushed", "design-needs-changing", "not-needed"],
    "review": ["ship", "changes-wanted"],
    "review-protected": ["ship", "changes-wanted"],
    "fact-check": ["ship", "changes-wanted"],
    "merge": ["merged", "cannot-merge"],
}
MODELS = ("haiku", "sonnet", "opus", "fable")
FIXED = ("next-action", "person", "done")
WRITES, READS = {"design", "build"}, {"review", "review-protected", "fact-check"}


def slug(name):
    return str(name).strip().lower().replace(" ", "-")


def check(doc):
    bad, info = [], []
    if not isinstance(doc, dict) or not isinstance(doc.get("stages"), list) or not doc["stages"]:
        return ["the file needs a `stages:` list with at least one stage"], info
    for k in doc:
        if k not in ("format", "name", "stages", "max-moves"):
            bad.append(f"unknown key at the top: `{k}`")
    if doc.get("format") != 2:
        bad.append("`format: 2` is required")
    mm = doc.get("max-moves", 25)
    if not isinstance(mm, int) or isinstance(mm, bool) or mm < 2:
        bad.append("`max-moves` is a whole number, 2 or more (rule 10)")
    stages, takes = {}, {"design-first": [], "other": []}
    for i, st in enumerate(doc["stages"], 1):
        if not isinstance(st, dict) or not st.get("name"):
            bad.append(f"stage {i} has no name")
            continue
        nm = st["name"]
        for k in st:
            if k not in ("name", "model", "takes", "actions", "stuck"):
                hint = " (outcomes are written under their action, not under `next:`)" if k == "next" else ""
                bad.append(f"{nm}: unknown key `{k}`{hint}")
        key = slug(nm)
        if key in stages or key in FIXED:
            bad.append(f"{nm}: the name is already used, or is a reserved word (rule 8)")
            continue
        acts = []
        for a in st.get("actions") or []:
            if isinstance(a, str):
                a = {a: {}}
            if not isinstance(a, dict) or len(a) != 1 or next(iter(a)) not in OUT:
                bad.append(f"{nm}: unknown action {a!r}; the actions are {', '.join(OUT)}")
                continue
            name, outs = next(iter(a.items()))
            if outs is None:
                outs = {}
            if not isinstance(outs, dict):
                bad.append(f"{nm}: under `{name}` write its outcomes as `outcome: destination`")
                outs = {}
            acts.append((name, outs))
        names = [n for n, _ in acts]
        if not acts:
            bad.append(f"{nm}: a stage needs at least one action (rule 8)")
        if st.get("model") not in MODELS:
            bad.append(f"{nm}: model must be one of {', '.join(MODELS)} (rule 8)")
        if set(names) & WRITES and set(names) & READS:
            bad.append(f"{nm}: a review or fact-check cannot share a stage with design or build (rule 5)")
        if "merge" in names and set(names) & WRITES and names.index("merge") < max(i for i, n in enumerate(names) if n in WRITES):
            bad.append(f"{nm}: merge comes before the action that opens the pull request (rule 6)")
        t = st.get("takes")
        if t not in (None, "design-first", "other", "any"):
            bad.append(f"{nm}: takes must be design-first, other or any")
        for kind in takes:
            if t in (kind, "any"):
                takes[kind].append(nm)
        stages[key] = {"name": nm, "acts": acts, "names": names, "stuck": st.get("stuck"), "edges": [], "asks": [], "pr_to_person": False}
    for kind, who in takes.items():
        if len(who) != 1:
            bad.append(f"new `{kind}` entries need exactly one stage that takes them; found {len(who)} (rule 7)")

    def dest(st, where, v, action_i=None):
        """Record one move; return nothing."""
        lim, answers = None, None
        if isinstance(v, dict):
            extra = set(v) - {"to", "limit", "answers"}
            if "to" not in v or extra:
                bad.append(f"{st['name']}: `{where}` must be a destination, {{to: …, limit: n}} or {{to: person, answers: {{…}}}}")
                return
            lim, answers, v = v.get("limit"), v.get("answers"), v["to"]
            if lim is not None and (not isinstance(lim, int) or isinstance(lim, bool) or lim < 1):
                bad.append(f"{st['name']}: `{where}`: a limit is a whole number, 1 or more")
                return
            if answers is not None and v != "person":
                bad.append(f"{st['name']}: `{where}`: answers belong only with `to: person`")
            if lim is not None and v in FIXED:
                bad.append(f"{st['name']}: `{where}`: a limit sits on a move to a stage, not to `{v}`")
        if not isinstance(v, str):
            bad.append(f"{st['name']}: `{where}` has no readable destination")
            return
        v = v if v in FIXED else slug(v)
        o = where.split(".")[-1]
        if v == "next-action":
            if action_i is None or action_i == len(st["acts"]) - 1:
                bad.append(f"{st['name']}: `{where}: next-action` has no following action in this stage (rule 1)")
            elif o == "branch-pushed" and st["names"][action_i + 1] != "build":
                bad.append(f"{st['name']}: `{where}`: branch-pushed needs `build` as the next action")
        elif v == "person":
            st["asks"].append(where)
            if o in ("pull-request-open", "ship"):
                st["pr_to_person"] = True
            for label, a in (answers or {}).items():
                a = a if a in FIXED else slug(a)
                if a not in stages and a not in ("done", "person"):
                    bad.append(f"{st['name']}: `{where}`: the answer {label!r} goes to `{a}`, which is not a stage (rule 1)")
                elif a in stages:
                    st["edges"].append((where, a, "person"))
        elif v != "done":
            if v not in stages:
                bad.append(f"{st['name']}: `{where}` goes to `{v}`, which is not a stage (rule 1)")
                return
            st["edges"].append((where, v, lim))
            if o == "branch-pushed" and "build" not in stages[v]["names"]:
                bad.append(f"{st['name']}: `{where}`: branch-pushed must go to a stage that has build")

    for st in stages.values():
        for i, (name, outs) in enumerate(st["acts"]):
            for o in outs:
                if o not in OUT[name]:
                    home = [a for a in st["names"] if o in OUT[a]]
                    hint = f"; it belongs under `{home[0]}`" if home else ("; `stuck` is a key of the stage" if o == "stuck" else "")
                    bad.append(f"{st['name']}: `{o}` is not an outcome of `{name}`{hint} (rule 2)")
            for o in OUT[name]:
                dest(st, f"{name}.{o}", outs.get(o, "done" if o == "merged" else "person"), i)
        dest(st, "stuck", st["stuck"] if st["stuck"] is not None else "person")

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

    def reach(k):
        seen, todo = {k}, [k]
        while todo:
            for _, v, _ in stages[todo.pop()]["edges"]:
                if v not in seen:
                    seen.add(v)
                    todo.append(v)
        return seen

    for key, st in stages.items():
        if set(st["names"]) & WRITES:
            r = reach(key)
            if not any("merge" in stages[k]["names"] or stages[k]["pr_to_person"] for k in r):
                bad.append(f"{st['name']}: its pull request can never reach a merge or the person (rule 4)")
    entered = {v for st in stages.values() for _, v, _ in st["edges"]} | {slug(n) for who in takes.values() for n in who}
    for key, st in stages.items():
        if key not in entered:
            bad.append(f"{st['name']}: nothing can reach this stage (rule 9)")
    wm = {doc_st.get("model") for doc_st in doc["stages"] if isinstance(doc_st, dict) and set(stages.get(slug(doc_st.get("name", "")), {}).get("names", [])) & WRITES}
    for doc_st in doc["stages"]:
        st = stages.get(slug(doc_st.get("name", ""))) if isinstance(doc_st, dict) else None
        if st and set(st["names"]) & READS and doc_st.get("model") in wm:
            info.append(f"warning: {st['name']} reviews on {doc_st.get('model')}, the same model as a stage that writes")
    info.append(f"an entry goes to the person after {mm} moves between stages, wherever it is")
    for st in stages.values():
        if st["asks"]:
            info.append(f"{st['name']}: goes to the person on {', '.join(st['asks'])}")
    return bad, info


if __name__ == "__main__":
    try:
        doc = yaml.safe_load(open(sys.argv[1]))
    except Exception as e:  # noqa: BLE001
        print(f"PROBLEM: the file is not valid YAML: {e}")
        sys.exit(1)
    bad, info = check(doc)
    bad = list(dict.fromkeys(bad))
    for b in bad:
        print("PROBLEM:", b)
    if not bad:
        for i in info:
            print("info:", i)
    print("OK" if not bad else f"{len(bad)} problem(s)")
    sys.exit(1 if bad else 0)
