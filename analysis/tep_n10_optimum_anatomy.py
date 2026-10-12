"""What does the OPTIMUM look like on the n10 cells our primal route misses by more than 5%? (d439)

The audit in `tep_primal_n10_audit.py` established that on R201, R202, R203 and RC201 the selected
trip partition genuinely needs two cars -- capping the fleet at one makes the chaining infeasible
-- and that the composition heuristic's partition needs two (or three) as well. So the shortfall is
not a chaining failure and not one bad partition; on the evidence so far, every partition we can
produce needs two cars while K reach an optimum we are 28 to 39 percent above.

That leaves one question the artifacts cannot answer: HOW MANY CARS DOES THE OPTIMUM USE? If it
uses two, our fleet is right and the loss is all street cost. If it uses one, then a one-car
solution exists and the selection stage is discarding it.

n10 is small enough to settle this by solving K's own joint MILP to proven optimality and reading
the answer off the solution. That also re-derives K's published objective independently, which is
a check on our instance build.

We disclaim the use of the predecessors' formulation and code: `joint_model_cplex` is our
transcription of their joint model, and `build_instance` builds their instances.

    python analysis/tep_n10_optimum_anatomy.py --cells R201,R202,R203,RC201,R204
"""
import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from k_comparison import k_proximity
from stamp import stamped


def k_inc(size, cell):
    d = json.load(io.open(os.path.join(ROOT, "runs", "oracle", "k_targets_small.json"), encoding="utf-8"))["n%d" % size]
    for r in d["rows"]:
        if r["cell"] == cell:
            return float(r["k_inc"]), bool(r["proven"])
    return None, None


def solve_exact(cell, size, tl, threads):
    from solver.config import InstanceSpec
    from solver.problem import SolverProblem
    from joint_model_cplex import build_joint_model, _extract_solution
    prob = SolverProblem(InstanceSpec(cell, size))
    h = build_joint_model(prob.raw)
    m = h.m
    m.parameters.timelimit = tl
    m.parameters.mip.tolerances.mipgap = 0.0
    m.parameters.threads = threads
    t0 = time.time()
    sol = m.solve(log_output=False)
    wall = time.time() - t0
    sd = m.solve_details
    if sol is None:
        return dict(obj=None, wall=round(wall, 1), status=str(sd.status if sd else "none"), closed=False)
    out = _extract_solution(h)
    # _extract_solution does not carry the objective; without it the verifier has nothing to
    # recompute against and reports a blocking finding that looks like a rejection of the
    # solution (d439 -- it made four proven optima read as verifier FAIL).
    out["objVal"] = round(float(sol.objective_value), 4)
    gap = getattr(sd, "mip_relative_gap", None)
    return dict(obj=float(sol.objective_value), out=out, wall=round(wall, 1),
                status=str(sd.status if sd else "none"),
                closed=bool(gap is not None and gap <= 1e-6), gap=gap)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="R201,R202,R203,RC201,R204")
    ap.add_argument("--size", type=int, default=10)
    ap.add_argument("--tl", type=float, default=900.0); ap.add_argument("--threads", type=int, default=2)
    a = ap.parse_args()
    prox = k_proximity(a.size)
    rows = {}
    for cell in a.cells.split(","):
        ki, proven = k_inc(a.size, cell)
        r = solve_exact(cell, a.size, a.tl, a.threads)
        ours = None
        p = os.path.join(ROOT, "runs", "postpass", "ipchain_%s_n%d.json" % (cell, a.size))
        if os.path.exists(p):
            ours = json.load(io.open(p, encoding="utf-8"))
        if r["obj"] is None:
            print("%-7s exact solve returned nothing (%s, %.0fs)" % (cell, r["status"], r["wall"]), flush=True)
            rows[cell] = dict(k_inc=ki, exact=None); continue
        o = r["out"]
        inst = V.load_instance(cell, a.size, prox)
        run = V.verify_solution(inst, o, cell=cell, size=a.size, proximity=prox, label="exact_joint")
        bad = [x for x in run.findings if x.severity != "TOLERANCE"]
        ok = (not bad) and (not run.blocking)
        print("%-7s EXACT %.3f (%s, gap %.1e, %.0fs) cars %s vessels %s | verifier3 %s | K publish %.2f (diff %+.3f) | ours %s cars %s (%+.2f%%)"
              % (cell, r["obj"], "PROVEN OPTIMAL" if r["closed"] else "NOT closed", r.get("gap") or 0, r["wall"],
                 o.get("nCars"), o.get("nVessel"), "PASS" if ok else "FAIL", ki, r["obj"] - ki,
                 ("%.3f" % ours["objVal"]) if ours else "-", ours.get("nCars") if ours else "-",
                 (100.0 * (ours["objVal"] / r["obj"] - 1)) if ours else float("nan")), flush=True)
        rows[cell] = dict(k_inc=ki, k_proven=proven, exact=r["obj"], exact_closed=r["closed"],
                          exact_cars=o.get("nCars"), exact_vessels=o.get("nVessel"),
                          exact_fleet=o.get("FleetStreet"), exact_travel=o.get("TravelStreet"),
                          exact_verified=ok, wall=r["wall"],
                          ours=(float(ours["objVal"]) if ours else None),
                          our_cars=(int(ours["nCars"]) if ours else None))
    print()
    same = [c for c, r in rows.items() if r.get("exact") is not None and abs(r["exact"] - r["k_inc"]) <= 0.05]
    print("  our exact solve reproduces K's published optimum on %d of %d cells (+-0.05)" % (len(same), len(rows)))
    fleetdiff = [(c, r["exact_cars"], r["our_cars"]) for c, r in rows.items()
                 if r.get("exact_cars") is not None and r.get("our_cars") is not None and r["exact_cars"] != r["our_cars"]]
    if fleetdiff:
        print("  THE OPTIMUM USES A DIFFERENT FLEET on %d cell(s): %s"
              % (len(fleetdiff), ", ".join("%s optimum %d vs ours %d" % t for t in fleetdiff)))
    else:
        print("  the optimum uses the SAME fleet as our route everywhere; the whole loss is street cost")
    out = os.path.join(ROOT, "runs", "oracle", "tep_n%d_optimum_anatomy.json" % a.size)
    json.dump(stamped(dict(size=a.size, cells=rows)), io.open(out, "w", encoding="utf-8"), indent=1)
    print("  wrote %s" % os.path.relpath(out, ROOT))


if __name__ == "__main__":
    main()
