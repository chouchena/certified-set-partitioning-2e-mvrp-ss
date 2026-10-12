"""The relaxed exact model as a BOUND INSTRUMENT at n100 -- stage 1, the linear relaxation (d447).

WHY THIS EXISTS. The full joint linear relaxation has been computed at n100 exactly twice, on
C201 and R208, while triaging a cut inventory on 2026-09-22. The question asked there was whether
the fleet-floor row lifts the relaxation; it does, by +327.7 and +350.5. The DIFFERENT question --
is this relaxation a better bound than our own descent leg? -- was never asked. Put side by side:

    C201   joint LP + fleet floor 1975.8   against our descent 2656.2   (we win)
    R208   joint LP + fleet floor 1091.5   against our descent  850.5   (IT WINS, by 28%)

At n100 we currently report no TEP bound at all, so an instrument that beats the descent on any
cell there is worth knowing about. This runs it on six cells chosen by where the current bound has
the most room, and on the two known cells to reproduce them.

WHAT IS AND IS NOT AT STAKE IN THE RUNTIME. The linear relaxation's VALUE is deterministic: it is
the optimum of a linear program and does not depend on the clock, the thread count or what else
is on the machine. So this stage may run in parallel and its numbers are unaffected. Only its wall
time is co-tenanted, and no wall time from this stage is reported. The capped INTEGER solve, whose
value is time-dependent, is stage 2 and is deliberately not run here.

VALIDITY. The joint model is our transcription of the predecessors' formulation, and its linear
relaxation is a relaxation of the problem, so its optimum is a valid lower bound. The fleet-floor
row `nofCars >= V_LB` is valid independently (`crossfeed/fullset_bound`), so adding it keeps the
bound valid and can only raise it. We disclaim the use of their formulation throughout.

    python analysis/joint_lp_bound_n100.py --cells R208 --size 100        # one cell, measure memory
    python analysis/joint_lp_bound_n100.py --workers 4                    # the rest
"""
import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped

CELLS = ["C201", "C204", "R208", "R209", "R211", "RC208"]


def peak_mb():
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / (1024 * 1024))
    except Exception:
        return None


def one(cell, size, tl):
    from solver.config import InstanceSpec
    from solver.problem import SolverProblem
    from joint_model_cplex import build_joint_model
    from docplex.mp.relax_linear import LinearRelaxer
    from crossfeed.fullset_bound import fullset_bound

    prob = SolverProblem(InstanceSpec(cell, size))
    vlb = int(fullset_bound(prob.raw)[1]["V_LB"])
    out = dict(cell=cell, size=size, V_LB=vlb)

    for tag, with_cut in (("plain", False), ("fleetfloor", True)):
        t0 = time.time()
        h = build_joint_model(prob.raw)          # a fresh model per arm, so they cannot interact
        if with_cut:
            h.m.add_constraint(h.nofCars >= vlb, ctname="fleet_floor")
        build_s = time.time() - t0
        out.setdefault("rows", h.m.number_of_constraints)
        out.setdefault("cols", h.m.number_of_variables)
        rel = LinearRelaxer.make_relaxed_model(h.m)
        rel.parameters.timelimit = tl
        rel.parameters.threads = 1
        t0 = time.time()
        s = rel.solve(log_output=False)
        secs = time.time() - t0
        out[tag] = dict(value=(float(s.objective_value) if s else None),
                        status=str(rel.solve_details.status if rel.solve_details else "none"),
                        build_secs=round(build_s, 1), solve_secs=round(secs, 1))
        print("  %-6s %-11s %s  (build %.0fs, solve %.0fs)" % (
              cell, tag, ("%.2f" % out[tag]["value"]) if out[tag]["value"] is not None else out[tag]["status"],
              build_s, secs), flush=True)
        del rel, h
    out["peak_mb"] = peak_mb()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default=None); ap.add_argument("--size", type=int, default=100)
    ap.add_argument("--tl", type=float, default=1800.0)
    a = ap.parse_args()
    cells = a.cells.split(",") if a.cells else CELLS
    import dual_vs_k as D
    rows = []
    for c in cells:
        print("\n=== %s n%d ===" % (c, a.size), flush=True)
        try:
            r = one(c, a.size, a.tl)
        except Exception as e:
            print("  FAILED: %s: %s" % (type(e).__name__, e), flush=True)
            rows.append(dict(cell=c, size=a.size, error="%s: %s" % (type(e).__name__, e))); continue
        d = D.lb_frontier(c, a.size) or D.lb_maxrec(c, a.size)
        r["descent"] = float(d) if d else None
        best = r.get("fleetfloor", {}).get("value")
        if best is not None and r["descent"]:
            r["vs_descent"] = best / r["descent"]
            print("  %-6s joint LP + fleet floor %.2f vs descent %.2f -> %.3fx  %s"
                  % (c, best, r["descent"], r["vs_descent"],
                     "IT WINS" if r["vs_descent"] > 1 else "descent holds"), flush=True)
        rows.append(r)
    ok = [r for r in rows if r.get("vs_descent")]
    if ok:
        w = [r for r in ok if r["vs_descent"] > 1]
        print("\n  the relaxed exact model beats the descent on %d of %d cells" % (len(w), len(ok)))
        print("  ratios: " + ", ".join("%s %.3fx" % (r["cell"], r["vs_descent"]) for r in sorted(ok, key=lambda x: -x["vs_descent"])))
        mem = [r["peak_mb"] for r in rows if r.get("peak_mb")]
        if mem:
            print("  peak resident memory per cell: %s MB" % max(mem))
    p = os.path.join(ROOT, "runs", "oracle", "joint_lp_bound_n%d.json" % a.size)
    json.dump(stamped(dict(size=a.size, rows=rows)), io.open(p, "w", encoding="utf-8"), indent=1)
    print("  wrote %s" % os.path.relpath(p, ROOT))


if __name__ == "__main__":
    main()
