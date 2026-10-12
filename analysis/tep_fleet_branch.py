"""Is the integer-car CUT valid? A fixed-pool branch test (d442).

`tep_cg_bound.py` adds `N >= ceil(N_LP)` and calls the result proven. Its written justification is
"the proven LP's car count N_LP is a lower bound on the cars of every feasible solution". That does
not follow. The LP minimises `penalty * N + travel`, so it buys an extra car whenever the travel
saving exceeds the penalty. An integer solution using FEWER cars and more travel is LP-feasible,
and nothing shown so far rules out its being cheaper than the value the cut then reports. A cut
discards that side; a BRANCH does not, because `N <= floor(N_LP)` and `N >= ceil(N_LP)` partition
the feasible set and the minimum over the two children is a bound whatever the truth is.

WHAT THIS SCRIPT DOES, AND WHAT IT CANNOT DO. It converges the master once, then re-solves each
child over THAT SAME COLUMN POOL. Both children therefore see identical columns, which makes the
comparison between them fair, and a `N <= floor` child that comes out CHEAPER is direct evidence
that the cut discards a cheaper region. What it is not: a bound. Each child would need its own
re-pricing to convergence for its value to be a bound over all columns, and that needs a branch
constraint applied before the column-generation loop, which is a change to `tep_cg_bound.py` and
is deliberately not made here while runs are in flight.

So: a NEGATIVE here (the floor child is cheaper) refutes the cut's justification on the evidence
available. A POSITIVE here does not establish it.

    python analysis/tep_fleet_branch.py --cells R204,R208,RC203,R211 --size 20
"""
import argparse
import io
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from k_comparison import k_proximity
import tep_cg_bound as T
from stamp import stamped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="R204,R208,RC203,R211"); ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--ng", type=int, default=10); ap.add_argument("--max-secs", type=float, default=600.0)
    a = ap.parse_args()
    out, refuted, safe, integral = {}, [], [], []
    for cell in a.cells.split(","):
        prox = k_proximity(a.size)
        inst = V.load_instance(cell, a.size, prox)
        delta = T.default_delta(inst)
        r0 = T.run(cell, delta, 400, ["prio", "ts"], a.ng, 1000, False, 3_000_000, size=a.size,
                   start_states=True, proximity=prox, return_master=True, max_secs=a.max_secs)
        M = r0["master"]; lp0 = float(r0["lp_street"]); n0 = float(r0["N"])
        lo, hi = int(math.floor(n0 + 1e-6)), int(math.ceil(n0 - 1e-6))
        print("\n%s n%d  parent LP %.4f  N %.3f  proven %s" % (cell, a.size, lp0, n0, r0["proven"]), flush=True)
        if hi - lo < 1:
            print("  N is integral at the parent -- the cut never fires here")
            integral.append(cell); out[cell] = dict(parent=lp0, N=n0, integral=True); continue

        def child(sense, k):
            c = M.m.addConstr(M.N >= k if sense == "ge" else M.N <= k, name="br")
            M.m.optimize()
            v = M.m.ObjVal if M.m.Status == 2 else None
            nn = M.N.X if M.m.Status == 2 else None
            M.m.remove(c); M.m.update(); M.m.optimize()
            return v, nn

        vg, ng_ = child("ge", hi)
        vl, nl = child("le", lo)
        print("  N >= %-2d  ->  %s" % (hi, ("%.4f  (N %.3f)" % (vg, ng_)) if vg is not None else "INFEASIBLE"))
        print("  N <= %-2d  ->  %s" % (lo, ("%.4f  (N %.3f)" % (vl, nl)) if vl is not None else "INFEASIBLE"))
        vals = [x for x in (vg, vl) if x is not None]
        br = min(vals) if vals else None
        verdict = ""
        if vg is not None and vl is not None and vl < vg - 1e-6:
            verdict = "CUT OVER-STATES by %.4f (%.2f%%)" % (vg - vl, 100.0 * (vg / vl - 1)); refuted.append(cell)
        elif vl is None:
            verdict = "floor side INFEASIBLE -- the cut is safe on this cell"; safe.append(cell)
        else:
            verdict = "ceil side is the weaker child -- the cut equals the branch bound here"; safe.append(cell)
        print("  cut would report %s ; branch bound is %s  ->  %s"
              % (("%.4f" % vg) if vg is not None else "INFEASIBLE", ("%.4f" % br) if br else "-", verdict))
        out[cell] = dict(parent=lp0, N=n0, lo=lo, hi=hi, child_ge=vg, child_le=vl,
                         branch_bound=br, cut_value=vg, verdict=verdict)
    print("\n  over %d cells: cut over-states on %d %s; safe on %d; N already integral on %d"
          % (len(out), len(refuted), refuted or "", len(safe), len(integral)))
    print("  NOTE: fixed pool. A negative refutes the cut's justification; a positive does not establish it.")
    p = os.path.join(ROOT, "runs", "oracle", "tep_fleet_branch_n%d.json" % a.size)
    json.dump(stamped(dict(size=a.size, fixed_pool=True, cells=out, refuted=refuted)),
              io.open(p, "w", encoding="utf-8"), indent=1)
    print("  wrote %s" % os.path.relpath(p, ROOT))


if __name__ == "__main__":
    main()
