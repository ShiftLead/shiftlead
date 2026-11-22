"""Check a flow file (TD-1954 trial, third cut: one kind of work per stage). Usage: flowcheck.py <flow.yml>."""

import re
import sys

import yaml

OUT = {
    "design": ["work-pushed", "not-needed"],
    "build": ["work-pushed", "design-needs-changing", "not-needed"],
    "review": ["ship", "changes-wanted"],
}
MODELS = ("haiku", "sonnet", "opus", "fable")
FIXED = ("person", "done", "merge")
CAN_MERGE = ("work-pushed", "ship")
WRITES = ("design", "build")
SUPPORT = ("tech-lead", "board-answers", "unheld-pull-requests", "manager", "sweeper")
STAGE_KEYS = ("name", "does", "model", "takes", "only-when", "brief", "also")
EVERY = re.compile(r"^([1-9]\d*) (merged-pull-requests|hours|days)$")


def slug(name):
    return str(name).strip().lower().replace(" ", "-")


def check(doc):
    bad, info = [], []
    if not isinstance(doc, dict) or not isinstance(doc.get("stages"), list) or not doc["stages"]:
        return ["the file needs a `stages:` list with at least one stage"], info
    for k in doc:
        if k not in ("format", "name", "stages", "audits", "support", "max-moves"):
            bad.append(f"unknown key at the top: `{k}`")
    for seat, model in (doc.get("support") or {}).items():
        if seat not in SUPPORT or model not in MODELS:
            bad.append(f"support: `{seat}: {model}` must be one of {', '.join(SUPPORT)} with a model from the list")
    if doc.get("format") != 3:
        bad.append("`format: 3` is required")
    mm = doc.get("max-moves", 25)
    if not isinstance(mm, int) or isinstance(mm, bool) or mm < 2:
        bad.append("`max-moves` is a whole number, 2 or more (rule 9)")

    stages, takes, audits = {}, {"design-first": [], "other": []}, {}
    for i, a in enumerate(doc.get("audits") or [], 1):
        if not isinstance(a, dict) or not a.get("name"):
            bad.append(f"audit {i} has no name")
            continue
        nm = a["name"]
        for k in a:
            if k not in ("name", "model", "every", "brief", "also"):
                bad.append(f"{nm}: unknown key `{k}`; an audit has name, model, every, brief and also (rule 10)")
        if a.get("model") not in MODELS:
            bad.append(f"{nm}: model must be one of {', '.join(MODELS)} (rule 10)")
        if not EVERY.match(str(a.get("every", ""))):
            bad.append(f"{nm}: `every` is written like `10 merged-pull-requests`, `6 hours` or `1 days` (rule 10)")
        if not a.get("brief"):
            bad.append(f"{nm}: an audit needs a `brief:`: docs, tests, code, or the name of a brief of your own (rule 10)")
        if slug(nm) in audits or slug(nm) in FIXED:
            bad.append(f"{nm}: the name is already used, or is a reserved word (rule 7)")
        audits[slug(nm)] = nm

    for i, st in enumerate(doc["stages"], 1):
        if not isinstance(st, dict) or not st.get("name"):
            bad.append(f"stage {i} has no name")
            continue
        nm, kind = st["name"], st.get("does")
        key = slug(nm)
        if key in stages or key in FIXED or key in audits:
            bad.append(f"{nm}: the name is already used, or is a reserved word (rule 7)")
            continue
        if kind not in OUT:
            hint = "; an audit goes in the `audits:` list" if kind in ("audit", "hunt") else ""
            hint = "; merge is a destination, not a stage" if kind == "merge" else hint
            hint = "; a stage does one kind of work, so write two stages" if isinstance(kind, list) else hint
            bad.append(f"{nm}: `does` must be one of {', '.join(OUT)}{hint} (rule 7)")
            continue
        if st.get("model") not in MODELS:
            bad.append(f"{nm}: model must be one of {', '.join(MODELS)} (rule 7)")
        outs = {}
        for k, v in st.items():
            if k in STAGE_KEYS:
                continue
            if k in OUT[kind] or k == "other":
                outs[k] = v
            elif any(k in o for o in OUT.values()):
                bad.append(f"{nm}: `{k}` is not an outcome of a {kind} stage; its outcomes are {', '.join(OUT[kind])} and other (rule 2)")
            elif k in ("actions", "next", "stuck"):
                tip = {"actions": "a stage does one kind of work, named by `does:`", "next": "outcomes are keys of the stage itself", "stuck": "the catch-all outcome is `other`"}[k]
                bad.append(f"{nm}: unknown key `{k}`; {tip}")
            else:
                bad.append(f"{nm}: unknown key `{k}`")
        t = st.get("takes")
        if t not in (None, "design-first", "other", "any"):
            bad.append(f"{nm}: takes must be design-first, other or any")
        elif t and kind == "review":
            bad.append(f"{nm}: a review stage cannot take new entries; it reads work another stage pushed (rule 6)")
        for k in takes:
            if t in (k, "any"):
                takes[k].append(nm)
        ow = st.get("only-when")
        if ow is not None and (kind != "review" or ow != "protected-files"):
            bad.append(f"{nm}: `only-when: protected-files` is the one value, and only on a review stage")
        stages[key] = {"name": nm, "kind": kind, "model": st.get("model"), "outs": outs, "edges": [], "asks": [], "ends": False}
    for kind, who in takes.items():
        if len(who) != 1:
            tip = "; a flow with no design stage writes `takes: any` on its first build stage" if kind == "design-first" and not who else ""
            bad.append(f"new `{kind}` entries need exactly one stage that takes them; found {len(who)}{tip} (rule 6)")

    def one(st, where, v, top=True):
        """Read one destination; record the move."""
        lim = answers = refused = None
        if isinstance(v, dict):
            extra = set(v) - {"to", "limit", "answers", "refused"}
            if "to" not in v or extra:
                bad.append(f"{st['name']}: `{where}` must be a destination, {{to: …, limit: n}}, {{to: merge, refused: …}} or {{to: person, answers: {{…}}}}")
                return
            lim, answers, refused, v = v.get("limit"), v.get("answers"), v.get("refused"), v["to"]
            if lim is not None and (not isinstance(lim, int) or isinstance(lim, bool) or lim < 1):
                bad.append(f"{st['name']}: `{where}`: a limit is a whole number, 1 or more")
                return
            if answers is not None and v != "person":
                bad.append(f"{st['name']}: `{where}`: answers belong only with `to: person`")
            if refused is not None and v != "merge":
                bad.append(f"{st['name']}: `{where}`: `refused` belongs only with `to: merge`")
            if lim is not None and v in FIXED:
                bad.append(f"{st['name']}: `{where}`: a limit sits on a move to a stage, not to `{v}`" + ("; put it on `refused`" if v == "merge" else ""))
        if not isinstance(v, str):
            bad.append(f"{st['name']}: `{where}` has no readable destination")
            return
        v = v if v in FIXED else slug(v)
        o = where.split(".")[0]
        if v == "merge":
            if not top:
                bad.append(f"{st['name']}: `{where}`: a refused merge cannot go to merge again")
            elif o not in CAN_MERGE:
                bad.append(f"{st['name']}: `{where}`: only `work-pushed` or `ship` can go to merge (rule 1)")
            else:
                st["ends"] = True
                one(st, f"{o}.refused", refused if refused is not None else "person", top=False)
        elif v == "person":
            st["asks"].append(where)
            if o in CAN_MERGE and top:
                st["ends"] = True
            for label, a in (answers or {}).items():
                a = a if a in FIXED else slug(a)
                if a in stages:
                    st["edges"].append((where, a, "person"))
                elif a != "person":
                    bad.append(f"{st['name']}: `{where}`: the answer {label!r} goes to `{a}`, which is not a stage (rule 1)")
        elif v == "done":
            tip = "send it to merge, a stage or the person" if o in CAN_MERGE else "leave it out so the person decides, or send it to a stage"
            bad.append(f"{st['name']}: `{where}: done` is not a destination; {tip} (rule 5)")
        elif v in audits:
            bad.append(f"{st['name']}: `{where}` goes to the audit `{v}`; an audit starts on its clock and nothing is sent to it (rule 1)")
        elif v not in stages:
            bad.append(f"{st['name']}: `{where}` goes to `{v}`, which is not a stage (rule 1)")
        else:
            st["edges"].append((where, v, lim))

    for st in stages.values():
        for o in OUT[st["kind"]] + ["other"]:
            one(st, o, st["outs"].get(o, "person"))

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
        if st["kind"] in WRITES:
            r = reach(key)
            if not any(stages[k]["ends"] for k in r):
                bad.append(f"{st['name']}: its pull request can never reach a merge or the person (rule 4)")
            for k in sorted(r - {key}):
                if stages[k]["kind"] == "review" and stages[k]["model"] == st["model"]:
                    info.append(f"warning: {stages[k]['name']} reviews on {st['model']}, the same model {st['name']} writes on")
    entered = {v for st in stages.values() for _, v, _ in st["edges"]} | {slug(n) for who in takes.values() for n in who}
    for key, st in stages.items():
        if key not in entered:
            bad.append(f"{st['name']}: nothing can reach this stage (rule 8)")
    info.append(f"an entry goes to the person after {mm} moves between stages, wherever it is")
    for st in stages.values():
        if st["asks"]:
            info.append(f"{st['name']}: goes to the person on {', '.join(st['asks'])}")
    for nm in audits.values():
        info.append(f"{nm}: an audit on its clock; `other` goes to the person")
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
        for i in dict.fromkeys(info):
            print("info:", i)
    print("OK" if not bad else f"{len(bad)} problem(s)")
    sys.exit(1 if bad else 0)
