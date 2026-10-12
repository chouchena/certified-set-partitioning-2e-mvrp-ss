"""Is the banked best-known's water optimal GIVEN its street? Proven per cell, not sampled. (d599)

WHY. I told the author the water side was "closed" on three cells. Three is not a grid, and the
author said so. This runs all 135.

WHAT IS PROVEN, and why it is a proof rather than a sample. `SubModel(problem.raw, sol["xij"],
sol["vi"], hubassign=True, integral=True)` is the exact synchronisation-plus-water subproblem for a
FIXED street routing and transfer set. Solved to `integer optimal` with gap 0.0, its incumbent IS
the optimum of that subproblem. So a cell where it returns the banked objective is a cell where the
banked water is provably optimal for its street -- not "no slack was found", but "no slack exists".

The status is read and reported per cell precisely because an exact match proves nothing if the
solve merely terminated at a limit holding the value it was handed. The first version of this
measurement did not read the status, and separately misreported the subproblem objective as the
water term; both are why this one prints `proven` and `status` for every cell.

WHAT THIS DOES NOT SHOW. Nothing about whether a DIFFERENT street would admit cheaper water. It
conditions on the street we have. That is the relevant question for "should an operator re-optimise
water at the tail", and it is not the question "should the two echelons be co-optimised".

    python analysis/water_optimality.py
    python analysis/water_optimality.py --sizes 30 50
"""
import argparse
import io
import json
import os
import statistics as st
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
sys.path.insert(0, os.path.join(ROOT, "solver"))
import verifier3 as V
from k_comparison import k_proximity
from best_known import best_solution
from solver.config import InstanceSpec
from solver.problem import SolverProblem
from crossfeed.lagrangian_subproblem import SubModel
from stamp import stamped

CELLS = (["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)]
         + ["RC%d" % i for i in range(201, 209)])
TOL = 0.05


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", nargs="*", type=int, default=[10, 20, 30, 50, 100])
    ap.add_argument("--time-limit", type=float, default=120.0)
    a = ap.parse_args()
    print("WATER OPTIMALITY -- is BK's water optimal given BK's street? exact re-solve, per cell\n")
    print("  %-6s %-5s %12s %12s %10s %7s %9s" % ("cell", "size", "BK obj", "exact", "slack", "proven", "secs"))
    rows = []
    for size in a.sizes:
        prox = k_proximity(size)
        for cell in CELLS:
            bs = best_solution(cell, size)
            if not bs:
                continue
            try:
                sol = json.load(io.open(os.path.join(ROOT, bs[2]), encoding="utf-8"))
                p = SolverProblem(InstanceSpec(cell, size, proximity=prox))
                p.raw.hardSingleTransfer = True
                p.raw.validBigM = True
                t0 = time.time()
                sub = SubModel(p.raw, sol["xij"], sol["vi"], hubassign=True, integral=True)
                r = sub.solve(time_limit=a.time_limit)
                secs = time.time() - t0
                exact = float(r.incumbent)
                proven = bool(getattr(r, "proven", False))
                slack = float(sol["objVal"]) - exact
                rows.append(dict(cell=cell, size=size, bk=float(sol["objVal"]), exact=exact,
                                 slack=slack, proven=proven, status=str(getattr(r, "status", "")),
                                 mip_gap=getattr(r, "mip_gap", None), secs=round(secs, 2)))
                print("  %-6s n%-4d %12.3f %12.3f %10.3f %7s %9.2f"
                      % (cell, size, float(sol["objVal"]), exact, slack, proven, secs), flush=True)
            except Exception as e:
                rows.append(dict(cell=cell, size=size, error="%s: %s" % (type(e).__name__, str(e)[:80])))
                print("  %-6s n%-4d  ERROR %s" % (cell, size, type(e).__name__), flush=True)
    print()
    print("  %-5s %7s %9s %11s %13s %13s" % ("size", "cells", "proven", "slack>%.2f" % TOL, "median slack", "max slack"))
    ok = [r for r in rows if "error" not in r]
    for size in a.sizes:
        rs = [r for r in ok if r["size"] == size]
        if not rs:
            continue
        sl = [r for r in rs if r["slack"] > TOL]
        print("  n%-4d %7d %9d %11d %13.3f %13.3f"
              % (size, len(rs), sum(1 for r in rs if r["proven"]), len(sl),
                 st.median([r["slack"] for r in rs]), max(r["slack"] for r in rs)))
    nslack = [r for r in ok if r["slack"] > TOL]
    nprov = [r for r in ok if not r["proven"]]
    print()
    print("  %d cell(s) | %d PROVEN optimal | %d with water slack | %d errored"
          % (len(ok), sum(1 for r in ok if r["proven"]), len(nslack), len(rows) - len(ok)))
    if nprov:
        print("  NOT PROVEN on %d cell(s) -- those establish nothing either way: %s"
              % (len(nprov), ", ".join("%s n%d" % (r["cell"], r["size"]) for r in nprov[:8])))
    if nslack:
        print("  SLACK FOUND on: %s"
              % ", ".join("%s n%d %+.2f" % (r["cell"], r["size"], r["slack"]) for r in nslack[:10]))
    else:
        print("  No cell has water slack. On the PROVEN cells that is a proof, not an absence of evidence.")
    p = os.path.join(ROOT, "runs", "oracle", "water_optimality.json")
    json.dump(stamped(dict(rows=rows, tol=TOL, time_limit=a.time_limit)),
              io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
