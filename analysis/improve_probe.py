"""Direct test: can a dedicated CPLEX search IMPROVE our best incumbent on the cells
where we lose worst to K?

This is the one intervention identified today and never actually tried at the CORRECT
instance. Every previous attempt was either tau-contaminated (build() default bug) or
cancelled. Here:
  * tau="formula" explicitly
  * fleet pinned to the incumbent's nCars (we are not dropping a car, we are searching
    the SAME fleet space for something better)
  * an upper cutoff just below our best, so CPLEX must find a strict improvement
  * emphasis 4 (hidden feasibility) -- the setting that worked
  * every FOUND solution dumped AND independently verified in-process
Outcome FOUND+CONFIRMED is a genuine primal improvement. Anything else is not.
"""
import sys, os, json, time, argparse
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R); sys.path.insert(0, os.path.join(R, "analysis"))
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped
from build_instance import build
from joint_model_cplex import build_joint_model, _extract_solution
from lp_component_anatomy import harvest
from solver.config import InstanceSpec
from solver.problem import SolverProblem

ap = argparse.ArgumentParser()
ap.add_argument("--cells", default="R203,RC203")
ap.add_argument("--size", type=int, default=20)
ap.add_argument("--tl", type=float, default=600)
ap.add_argument("--threads", type=int, default=4)
a = ap.parse_args()

best = harvest(set(a.cells.split(",")), a.size)
print(f"{'cell':7s} {'our best':>9s} {'nCars':>5s} {'cutoff':>9s} {'outcome':>10s} "
      f"{'new obj':>10s} {'gain':>8s} {'verify':>10s} {'wall':>6s}")
rows = []
for c in [x.strip() for x in a.cells.split(",")]:
    inc = best.get(c)
    if not inc:
        print(f"{c:7s}  no incumbent"); continue
    ob, nc = inc["objVal"], inc["nCars"]
    cut = ob - 0.05
    pr = build(c, a.size, tau="formula")
    H = build_joint_model(pr); m = H.m
    m.add_constraint(H.nofCars <= nc, ctname="fleet_cap")
    p = m.parameters
    p.timelimit = a.tl; p.threads = a.threads
    p.emphasis.mip.set(4)
    p.mip.tolerances.uppercutoff = cut      # force a STRICT improvement
    t0 = time.time(); s = m.solve(log_output=False); d = m.solve_details
    w = time.time() - t0
    out = obj = ver = None
    if s is not None:
        obj = s.objective_value; out = "FOUND"
        cand = _extract_solution(H); cand["objVal"] = round(obj, 4)
        sp = os.path.join(R, "runs", "solutions", f"improve_{c}_n{a.size}.json")
        json.dump(stamped(cand, __file__), open(sp, "w"), indent=1)
        vd = SolverProblem(InstanceSpec.for_k_comparison(c, a.size)).verify(cand)
        rec = getattr(vd, "recomputed_obj", None)
        ver = "CONFIRMED" if (bool(vd.ok) and (rec is None or abs(rec - obj) < 1e-3)) else "REJECTED"
    elif "infeasible" in (d.status or "").lower():
        out, ver = "INFEASIBLE", "proves our incumbent OPTIMAL at this fleet"
    else:
        out, ver = "TIMEOUT", "-"
    g = ("%+.2f%%" % ((obj - ob) / ob * 100)) if obj else "--"
    rows.append(dict(cell=c, ours=ob, nCars=nc, outcome=out, obj=obj, verify=ver, wall=w))
    print(f"{c:7s} {ob:9.2f} {nc:5d} {cut:9.2f} {out:>10s} "
          f"{('%10.2f'%obj) if obj else ' '*10} {g:>8s} {str(ver):>10s} {w:5.0f}s")
json.dump(stamped(rows, __file__), open(os.path.join(R, "runs", "improve_probe.json"), "w"), indent=1)
