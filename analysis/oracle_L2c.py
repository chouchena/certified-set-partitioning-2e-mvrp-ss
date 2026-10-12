"""L2c -- the OTHER direction. Does the model REJECT what verifier3 rejects?

WHAT WAS MISSING. L2b tests one implication:

    verifier3 ACCEPT  =>  model FEASIBLE        (catches an OVER-TIGHT model)

Nothing tested the converse:

    verifier3 REJECT  =>  model INFEASIBLE      (catches an UNDER-TIGHT model)

An under-tight model is missing a constraint, or has one transcribed too weakly. It admits
points K's model forbids, so our optimum can sit BELOW theirs on a solution they would never
accept -- and every incumbent we bank still passes verifier3, because verifier3 is a different
artifact that happens to have the row.

WHY THIS IS THE BEST AVAILABLE PROBE OF A SHARED MISREADING. verifier3 and the builder are two
independent transcriptions of the same article; verifier3 imports no builder. A misreading that
lives in only one of them shows up as DISAGREEMENT here. To survive, an error must be present in
BOTH artifacts, on the SAME row, in the SAME direction. That is strictly harder than a single
mistake, and it is as far as any self-check can go: what neither artifact ever knew, neither can
report. That residue is `oracle-residue-open`, and it is closed by reading, not running.

THE MATERIAL. analysis/impair30.py already built 30 incumbents, each breaking exactly one
published constraint, with verifier3's verdict recorded per artifact. This feeds them to the
model.

HONEST BOOKKEEPING. The round-trip pins only x, y, v, v_ip, h, u. An impairment that touches
nothing pinned -- a corrupted objective, an overstated fleet count -- cannot reach the model at
all, and reporting it as agreement would be a false pass. Those are reported NOT-PINNABLE and
excluded from the denominator.

    python analysis/oracle_L2c.py
"""
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

import verifier3

OUT = os.path.join(ROOT, "runs", "oracle")

# Impairments that alter only a REPORTED quantity, never a pinned decision variable. The model
# cannot see them by construction, so they are excluded rather than counted as agreement.
NOT_PINNABLE = {
    "OBJ": "the claimed objective is not a model variable we pin",
    "FLEET": "nCars / nVessel are free integers the model recomputes",
}


def dedup_report(sol):
    """Multiplicity present in the DUMP that pinning would silently collapse.

    A JSON list can name the same arc twice; the model has ONE binary variable per arc, so the
    duplicate has no encoding there and pinning a set would quietly drop it. Reporting that as
    'the model admits it' would be a false under-tightness finding, so it is detected instead.
    """
    out = {}
    for key, conv in (("xij", tuple), ("yij", tuple), ("vi", int)):
        v = sol.get(key) or []
        items = [conv(x) if conv is not int else int(x) for x in v]
        if len(items) != len(set(items)):
            out[key] = len(items) - len(set(items))
    return out


def binary_declared(H, which):
    """Is the property the dump broke enforced by the VARIABLE DECLARATION rather than a row?"""
    from gurobipy import GRB
    pool = {"xij": H["xij"], "yij": H["y"], "vi": H["vi"]}[which]
    vs = list(pool.values())
    return bool(vs) and all(v.VType == GRB.BINARY for v in vs)


def pin_result(path, tl=180.0, threads=4):
    """Pin a solution into the freshly built model. Returns (verdict, obj, detail)."""
    from build_instance import build
    from joint_model_gurobi import build_joint_model_gurobi
    from gurobipy import GRB
    sol = json.load(open(path, encoding="utf-8"))
    base = os.path.basename(path)
    mm = re.search(r"((?:RC|R|C)\d{3})_n(\d+)", base)
    cell, size = mm.group(1), int(mm.group(2))
    prox = float(sol["_proximity"])
    p = build(cell, size, wls=0.1, tau="formula", proximity=prox)
    p.hardSingleTransfer = bool(sol.get("_posts_26", True))
    H = build_joint_model_gurobi(p)
    m = H["m"]
    m.update()
    dups = dedup_report(sol)
    if dups:
        which = sorted(dups)[0]
        enforced = binary_declared(H, which)
        return ("NOT-EXPRESSIBLE", None,
                "%s carries %d duplicate entr%s; the model has one binary variable per item, so "
                "multiplicity has no encoding. Enforced by declaration: %s"
                % (which, dups[which], "y" if dups[which] == 1 else "ies",
                   "YES, every %s variable is BINARY" % which if enforced
                   else "NO -- and that IS a defect"))
    xsel = {(int(a), int(b)) for a, b in sol["xij"]}
    ysel = {(int(a), int(b)) for a, b in sol["yij"]}
    hub = dict(zip([int(c) for c in sol["vi"]], [int(q) for q in sol["hubs"]]))
    missing = sorted(xsel - set(H["xij"].keys())) + sorted(ysel - set(H["y"].keys()))
    if missing:
        return "INFEASIBLE", None, "%d arc(s) absent from the model" % len(missing)
    n = 0
    for key, var in H["xij"].items():
        m.addConstr(var == (1 if key in xsel else 0)); n += 1
    for key, var in H["y"].items():
        m.addConstr(var == (1 if key in ysel else 0)); n += 1
    for c, var in H["vi"].items():
        m.addConstr(var == (1 if c in hub else 0)); n += 1
    for (c, q), var in H["vip"].items():
        m.addConstr(var == (1 if hub.get(c) == q else 0)); n += 1
    for c, var in H["hi"].items():
        if str(c) in (sol.get("hi") or {}):
            m.addConstr(var == float(sol["hi"][str(c)])); n += 1
    for c, var in H["ui"].items():
        if str(c) in (sol.get("ui") or {}):
            m.addConstr(var == float(sol["ui"][str(c)])); n += 1
    m.Params.OutputFlag = 0
    m.Params.TimeLimit = tl
    m.Params.Threads = threads
    m.optimize()
    st = m.Status
    name = {GRB.OPTIMAL: "FEASIBLE", GRB.INFEASIBLE: "INFEASIBLE",
            GRB.INF_OR_UNBD: "INFEASIBLE", GRB.TIME_LIMIT: "TIME_LIMIT"}.get(st, "st%d" % st)
    return name, (m.ObjVal if st == GRB.OPTIMAL else None), "%d pinned" % n


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap_threads = 4
    manifest = [json.loads(l) for l in
                open(os.path.join(ROOT, "logs", "impair30.jsonl"), encoding="utf-8")]
    print("L2c -- does the MODEL reject what VERIFIER3 rejects? The under-tightness direction,")
    print("       and the best available probe of a misreading shared by both artifacts.")
    print()
    print("   %-3s %-46s %-9s %-13s %s" % ("c", "impairment", "verifier3", "model", "agreement"))
    rows, disagree, skipped = [], [], []
    t0 = time.time()
    for r in manifest:
        c = r["constraint"]
        art = os.path.join(ROOT, r["artifact"].replace("\\", os.sep))
        if not os.path.exists(art):
            skipped.append((c, "artifact missing"))
            continue
        cls = (r.get("expected_class") or "")
        why_skip = None
        for tag, reason in NOT_PINNABLE.items():
            if tag in cls:
                why_skip = reason
        v3 = verifier3.verify(art).verdict()
        if why_skip:
            print("   %-3d %-46s %-9s %-13s NOT-PINNABLE (%s)"
                  % (c, r["impairment"][:46], v3, "-", why_skip))
            skipped.append((c, why_skip))
            rows.append(dict(constraint=c, impairment=r["impairment"], verifier3=v3,
                             model=None, agree=None, excluded=why_skip))
            continue
        mv, obj, detail = pin_result(art, threads=ap_threads)
        if mv == "NOT-EXPRESSIBLE":
            good = "NO --" not in detail
            print("   %-3d %-46s %-9s %-13s %s"
                  % (c, r["impairment"][:46], v3, mv,
                     "not a model row (%s)" % detail.split("Enforced by declaration: ")[-1]
                     if good else "DECLARATION DOES NOT ENFORCE IT"))
            rows.append(dict(constraint=c, impairment=r["impairment"], verifier3=v3,
                             model=mv, agree=None if good else False, detail=detail))
            if good:
                skipped.append((c, "integrality/uniqueness is enforced by variable type"))
            else:
                disagree.append("(%d) %s: %s" % (c, r["impairment"], detail))
            continue
        if v3 == verifier3.REJECT:
            ok = (mv == "INFEASIBLE")
            verdict = "ok" if ok else "MODEL IS UNDER-TIGHT"
        elif v3 == verifier3.ACCEPT:
            ok = (mv == "FEASIBLE")
            verdict = "ok" if ok else "MODEL IS OVER-TIGHT"
        else:
            ok, verdict = None, "verifier3 %s -- no expectation" % v3
        print("   %-3d %-46s %-9s %-13s %s" % (c, r["impairment"][:46], v3, mv, verdict))
        if ok is False:
            disagree.append("(%d) %s: verifier3 %s, model %s -- %s"
                            % (c, r["impairment"], v3, mv, verdict))
        rows.append(dict(constraint=c, impairment=r["impairment"], verifier3=v3, model=mv,
                         obj=obj, agree=ok, detail=detail))

    tested = [r for r in rows if r.get("agree") is not None]
    agreed = [r for r in tested if r["agree"]]
    print()
    print("   tested %d   agree %d   DISAGREE %d   not pinnable %d"
          % (len(tested), len(agreed), len(disagree), len(skipped)))
    for d in disagree:
        print("      " + d)
    print()
    if not disagree and tested:
        print("   Two independently written transcriptions of K's constraints -- verifier3, which")
        print("   imports no builder, and joint_model_gurobi -- agree on all %d pinnable"
              % len(tested))
        print("   impairments, in BOTH directions. A misreading that survives this has to be")
        print("   present in both artifacts, on the same row, in the same direction.")
        print()
        print("   IT DOES NOT CLOSE oracle-residue-open. A constraint K state and NEITHER artifact")
        print("   ever encoded is invisible here by construction: both are silent and both agree.")
        print("   That residue is closed by reading the article, not by running anything.")
    json.dump(stamped({"rows": rows, "disagreements": disagree,
               "tested": len(tested), "agreed": len(agreed),
               "not_pinnable": [[c, w] for c, w in skipped],
               "wall_s": round(time.time() - t0, 1)}, __file__),
              open(os.path.join(OUT, "L2c.json"), "w"), indent=1, default=str)
    print("   %.1f min" % ((time.time() - t0) / 60))
    return 1 if disagree else 0


if __name__ == "__main__":
    sys.exit(main())
