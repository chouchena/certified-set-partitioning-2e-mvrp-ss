# ===================== RED FLAG -- TEP USE ONLY (2026-09-28) =====================
# This file REACHES K's FORMULATION (solver/engines/fixopt.py -> build_joint_model ->
# integratedJointModel). The standing constraint is that K's formulation is never part
# of our solution (d449, d451), and the fixopt-based work was archived and locked under
# archive/fixopt_locked/ on 2026-09-28.
#
# THIS FILE WAS NOT ARCHIVED because the admissible TEP path still depends on it.
# It is permitted ONLY where that dependency already exists. It must not be imported by
# new work, and no result derived from it may be reported without saying so.
#
# The load-bearing case: tep_cg_bound.master_ip calls assemble_precluster.retime, which
# builds K's joint model. So every master_ip result passes through K's formulation --
# which contradicts d451's claim that retime was replaced. Unresolved; see
# archive/fixopt_locked/LOCK.md.
# =================================================================================

"""STEP 2 -- does K's undersized big-M EXCLUDE a real solution at n50 and n100?

WHY A COUNT AND NOT A COMPARISON. Step 1 answers the question only where K publish proven optima,
which stops at n30. Above that nothing proves for anyone, so "is the valid-M optimum lower" cannot
be asked -- neither side has an optimum. Comparing incumbents at equal budget measures the
heuristic as much as the model, and at n100 a 60 s budget leaves both arms far from optimal, so
any difference is swamped by search noise.

THE DECISIVE TEST INSTEAD, and it needs neither optimality nor statistics. Run the VALID-M arm,
take each incumbent it finds, verify it independently, then PIN IT INTO THE FAITHFUL MODEL.

    faithful model says INFEASIBLE
        -> K's constants EXCLUDE a solution that is feasible for the article's model and that
           verifier3 accepts. That is direct proof the big-M bites at this size. One witness is
           enough; no budget argument weakens it, because the solution exists.

    faithful model ADMITS every incumbent
        -> not observed at this size, on these cells, at this budget. It does NOT show the
           constant is harmless: our search may simply never visit the excluded region, which is
           exactly why L2b could not find this and the arbiter could.

This is the arbiter's seed-0 mechanism applied at the sizes our own results live at.

SECONDARY, declared here so it is not a post-hoc addition: the paired objective delta across
seeds. At these sizes it bounds nothing -- both arms are budget-limited incumbents -- and no
claim rests on it.

    python analysis/step2_bigm_n50n100.py [--seeds 3] [--budget 300]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

import verifier3

OUT = os.path.join(ROOT, "runs", "oracle")
DUMPS = os.path.join(ROOT, "runs", "step2")
CELLS = ["C201", "R201", "RC201"]
SIZES = [50, 100]


def run_fixopt(cell, size, seed, valid, budget, det):
    arm = "validM" if valid else "faithfulM"
    dump = os.path.join(DUMPS, "s2_%s_%s_n%d_s%d.json" % (arm, cell, size, seed))
    log = os.path.join(ROOT, "logs", "step2_%s_%s_n%d_s%d.out" % (arm, cell, size, seed))
    cmd = [sys.executable, os.path.join(ROOT, "solver", "engines", "fixopt.py"),
           "--instance", cell, "--size", str(size), "--seed", str(seed),
           "--budget", str(budget), "--det-budget", str(det),
           "--variant", "step2" + arm, "--dump-best", dump]
    if not valid:
        cmd.append("--no-valid-bigm")
    with open(log, "w", encoding="utf-8") as fh:
        subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=ROOT)
    return dump if os.path.exists(dump) else None


def faithful_admits(path, tl=300.0, threads=4):
    """Pin a VALID-M incumbent into the FAITHFUL model. INFEASIBLE = the constant excludes it."""
    from build_instance import build
    from joint_model_gurobi import build_joint_model_gurobi
    from gurobipy import GRB
    sol = json.load(open(path, encoding="utf-8"))
    mm = re.search(r"((?:RC|R|C)\d{3})_n(\d+)", os.path.basename(path))
    cell, size = mm.group(1), int(mm.group(2))
    p = build(cell, size, wls=0.1, tau="formula", proximity=float(sol["_proximity"]))
    p.hardSingleTransfer = bool(sol.get("_posts_26", True))
    p.validBigM = False                      # K's constants -- the whole point
    H = build_joint_model_gurobi(p)
    m = H["m"]
    xsel = {(int(a), int(b)) for a, b in sol["xij"]}
    ysel = {(int(a), int(b)) for a, b in sol["yij"]}
    hub = dict(zip([int(c) for c in sol["vi"]], [int(q) for q in sol["hubs"]]))
    if (xsel - set(H["xij"].keys())) or (ysel - set(H["y"].keys())):
        return "CANNOT-REPRESENT"
    for key, var in H["xij"].items():
        m.addConstr(var == (1 if key in xsel else 0))
    for key, var in H["y"].items():
        m.addConstr(var == (1 if key in ysel else 0))
    for c, var in H["vi"].items():
        m.addConstr(var == (1 if c in hub else 0))
    for (c, q), var in H["vip"].items():
        m.addConstr(var == (1 if hub.get(c) == q else 0))
    for c, var in H["hi"].items():
        if str(c) in (sol.get("hi") or {}):
            m.addConstr(var == float(sol["hi"][str(c)]))
    for c, var in H["ui"].items():
        if str(c) in (sol.get("ui") or {}):
            m.addConstr(var == float(sol["ui"][str(c)]))
    m.Params.OutputFlag = 0
    m.Params.TimeLimit = tl
    m.Params.Threads = threads
    m.optimize()
    return {GRB.OPTIMAL: "ADMITS", GRB.INFEASIBLE: "EXCLUDES",
            GRB.INF_OR_UNBD: "EXCLUDES"}.get(m.Status, "status %d" % m.Status)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--budget", type=float, default=300.0)
    ap.add_argument("--det", type=float, default=600000.0)
    a = ap.parse_args()
    os.makedirs(DUMPS, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)

    print("STEP 2 -- does K's undersized big-M EXCLUDE a real solution at n50 / n100?")
    print("          Primary outcome is a WITNESS, not a comparison: pin each VALID-M incumbent")
    print("          into the FAITHFUL model. One INFEASIBLE is proof; no budget argument")
    print("          weakens it, because the solution exists and verifier3 accepts it.")
    print()
    print("   %-7s %5s %5s %-6s %12s %-9s %-16s" % ("cell", "n", "seed", "arm", "obj",
                                                    "verifier3", "faithful model"))
    rows, witnesses, t0 = [], [], time.time()
    for size in SIZES:
        for cell in CELLS:
            for seed in range(a.seeds):
                vp = run_fixopt(cell, size, seed, True, a.budget, a.det)
                fp = run_fixopt(cell, size, seed, False, a.budget, a.det)
                rec = dict(cell=cell, size=size, seed=seed)
                if vp:
                    vs = json.load(open(vp, encoding="utf-8"))
                    vrun = verifier3.verify(vp)
                    verdict = faithful_admits(vp)
                    rec.update(valid_obj=vs["objVal"], valid_verifier=vrun.verdict(),
                               valid_provenance=vrun.meta.get("provenance"),
                               faithful_model=verdict)
                    if verdict == "EXCLUDES" and vrun.verdict() == verifier3.ACCEPT:
                        witnesses.append("%s/n%d seed %d: obj %.3f, verifier3 ACCEPT, and the "
                                         "FAITHFUL model rules it INFEASIBLE"
                                         % (cell, size, seed, vs["objVal"]))
                    print("   %-7s %5d %5d %-6s %12.3f %-9s %-16s"
                          % (cell, size, seed, "valid", vs["objVal"], vrun.verdict(), verdict))
                if fp:
                    fs = json.load(open(fp, encoding="utf-8"))
                    rec["faithful_obj"] = fs["objVal"]
                    if rec.get("valid_obj") is not None:
                        rec["delta"] = rec["valid_obj"] - fs["objVal"]
                    print("   %-7s %5d %5d %-6s %12.3f %-9s %-16s"
                          % ("", size, seed, "faith", fs["objVal"], "-", ""))
                rows.append(rec)
                json.dump(stamped({"rows": rows, "witnesses": witnesses}, __file__),
                          open(os.path.join(OUT, "step2_bigm.json"), "w"), indent=1, default=str)

    print()
    print("   runs %d   WITNESSES (valid-M incumbent the faithful model excludes): %d"
          % (len(rows), len(witnesses)))
    for w in witnesses:
        print("      " + w)
    print()
    if witnesses:
        print("   FINDING. K's constants exclude solutions that are feasible for the model their")
        print("   article states, at the sizes our results live at. One witness suffices.")
    else:
        print("   NOT OBSERVED at these sizes, on these cells, at this budget. It does NOT show")
        print("   the constant is harmless: our search may never visit the excluded region --")
        print("   which is precisely why L2b could not find this and the arbiter could.")
    deltas = [r["delta"] for r in rows if r.get("delta") is not None]
    if deltas:
        neg = [d for d in deltas if d < -1e-6]
        print()
        print("   SECONDARY, bounding nothing at these sizes: paired delta over %d seeds, "
              "valid - faithful. negative %d, zero %d, positive %d."
              % (len(deltas), len(neg), sum(1 for d in deltas if abs(d) <= 1e-6),
                 sum(1 for d in deltas if d > 1e-6)))
        print("   Both arms are budget-limited incumbents here, so a sign means the search, not")
        print("   the model. No claim rests on it.")
    print()
    print("   total %.1f min" % ((time.time() - t0) / 60))
    return 0


if __name__ == "__main__":
    sys.exit(main())
