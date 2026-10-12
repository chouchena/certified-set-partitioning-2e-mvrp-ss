"""Ask CPLEX for a FEASIBLE solution at a reduced fleet count.

Instrument settled 2026-09-14 by control on RC208, where a one-car solution is
known to exist:
    emphasis 1 (feasibility)        -> 420 s, found NOTHING
    emphasis 4 (HIDDEN feasibility) -> 421 s, found obj 737.488
So emphasis 4 is the setting; emphasis 1 is not.

Model correctness was validated separately: handed the known one-car solution as
a MIP start, CPLEX accepts it and reports 693.868 exactly. The model and the
fleet constraint are right; finding the point from scratch is what is hard.

Target cells are those with a 2-car incumbent and NO known 1-car solution.
Outcomes:
  FOUND      a 1-car solution exists -- primal result, possibly large
  INFEASIBLE PROVED none exists -- valid fleet floor, dual result
  TIMEOUT    unknown. NEVER to be reported as infeasible.
"""
import sys, os, json, time, argparse
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R); sys.path.insert(0, os.path.join(R, "analysis"))
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped
from build_instance import build
from joint_model_cplex import build_joint_model
from lp_component_anatomy import harvest
from joint_model_cplex import _extract_solution
from solver.config import InstanceSpec
from solver.problem import SolverProblem

ap = argparse.ArgumentParser()
ap.add_argument("--cells", default="C204,C207,RC205")
ap.add_argument("--size", type=int, default=20)
ap.add_argument("--tl", type=float, default=600)
ap.add_argument("--threads", type=int, default=4)
ap.add_argument("--out", default="runs/fleet_drop_probe.json")
a = ap.parse_args()

cells = [c.strip() for c in a.cells.split(",")]
best = harvest(set(cells), a.size)
rows = []
print(f"{'cell':7s} {'incumbent':>10s} {'nCars':>5s} {'->':>3s} {'outcome':>11s} "
      f"{'new obj':>10s} {'delta%':>8s} {'wall':>7s}")
for c in cells:
    inc = best.get(c)
    if not inc:
        print(f"{c:7s}  no incumbent"); continue
    nc = inc["nCars"]; tgt = nc - 1
    pr = build(c, a.size, tau="formula")  # build() defaults to tau="code" (TD=0) -- MISMATCHES the verifier
    H = build_joint_model(pr); m = H.m
    m.add_constraint(H.nofCars <= tgt, ctname="fleet_drop")
    p = m.parameters
    p.timelimit = a.tl; p.threads = a.threads
    p.emphasis.mip.set(4)                       # hidden feasibility
    t0 = time.time(); s = m.solve(log_output=False); d = m.solve_details
    w = time.time() - t0
    st = (d.status or "").lower()
    if s is not None:
        o = s.objective_value
        out, dl = "FOUND", "%+.2f%%" % ((o - inc["objVal"]) / inc["objVal"] * 100)
        # DEFECT FIX 2026-09-14: dump AND independently verify, so a headline
        # result is never left resting on the solver's own word.
        try:
            cand = _extract_solution(H); cand["objVal"] = round(o, 4)
            sp = os.path.join(R, "runs", "solutions",
                              f"fleetdrop_{c}_n{a.size}_cars{tgt}.json")
            os.makedirs(os.path.dirname(sp), exist_ok=True)
            json.dump(stamped(cand, __file__), open(sp, "w"), indent=1)
            vd = SolverProblem(InstanceSpec.for_k_comparison(c, a.size)).verify(cand)
            rec = getattr(vd, "recomputed_obj", None)
            vok = bool(vd.ok) and (rec is None or abs(rec - o) < 1e-3)
            print(f"        verify: ok={bool(vd.ok)} recomputed={rec} -> "
                  f"{'CONFIRMED' if vok else 'REJECTED'}")
        except Exception as e:
            vok = None
            print(f"        verify FAILED to run: {str(e)[:120]}")
    elif "infeasible" in st:
        o, out, dl = None, "INFEASIBLE", "--"
    else:
        o, out, dl = None, "TIMEOUT", "--"
    rows.append(dict(cell=c, incumbent=inc["objVal"], from_cars=nc, to_cars=tgt,
                     outcome=out, obj=o, wall=w, status=d.status,
                     verified=(vok if s is not None else None)))
    print(f"{c:7s} {inc['objVal']:10.2f} {nc:5d} {tgt:3d} {out:>11s} "
          f"{('%10.2f'%o) if o else ' '*10} {dl:>8s} {w:6.0f}s")
os.makedirs(os.path.join(R, "runs"), exist_ok=True)
json.dump(stamped(rows, __file__), open(os.path.join(R, a.out), "w"), indent=1)
print("\nwrote", a.out)
