"""
verify_reduction_bound.py -- Rule 3 independent check of z_A(H)*.

For (cell, frontier k): rebuild the drop set from the easiness order, then solve
block-A(H) THREE ways and confirm the proven optimum agrees:
  1. CPLEX big-M              (the value used in the sweep)
  2. CPLEX indicator timing   (different formulation, same model)
  3. CP-SAT M-free            (different solver + formulation)
An agreement across all three that prove is strong independent confirmation.
"""
from __future__ import annotations
import sys, time
sys.path.insert(0, ".")
from build_instance import build
from crossfeed.block_a import BlockA
from crossfeed.easy_reduction import scarcity_and_weights, easiness
from crossfeed.blockA_cpsat import solve_blockA_cpsat, water_lb_scaled, SCALE

CASES = [("C203", 5), ("RC203", 6), ("C204", 6)]
SWEEP = {("C203", 5): 602.34, ("RC203", 6): 593.79, ("C204", 6): 466.24}


def dropset(name, k):
    p = build(name, 20, wls=0.1, tau="formula", proximity=0.0, time_limit=60)
    s, w, ctx = scarcity_and_weights(p)
    _e = easiness(ctx, w)
    return set(sorted(_e, key=lambda c: -_e[c])[:k]), p


def cplex(name, drop, timing, tl=900):
    p = build(name, 20, wls=0.1, tau="formula", proximity=0.0, time_limit=tl)
    ba = BlockA(p, integral=True, timing_mode=timing, drop=drop)
    try:
        ba.m.parameters.threads = 8
    except Exception:
        pass
    r = ba.solve(time_limit=tl, track_progress=False)
    return r["value"], bool(r["proven"]), r.get("status")


if __name__ == "__main__":
    for (nm, k) in CASES:
        drop, _ = dropset(nm, k)
        print(f"\n=== {nm} k={k}  drop={sorted(drop)}  sweep zA(H)*={SWEEP[(nm,k)]} ===", flush=True)
        t = time.time()
        v1, p1, s1 = cplex(nm, drop, "bigM")
        print(f"  CPLEX bigM     : {v1}  proven={p1}  ({s1})  {time.time()-t:.0f}s", flush=True)
        t = time.time()
        v2, p2, s2 = cplex(nm, drop, "indicator")
        print(f"  CPLEX indicator: {v2}  proven={p2}  ({s2})  {time.time()-t:.0f}s", flush=True)
        t = time.time()
        r3 = solve_blockA_cpsat(nm, 20, time_limit=900, workers=8, log=False, drop=drop)
        print(f"  CP-SAT M-free  : lb={r3['blockA_lb']} inc={r3['blockA_incumbent']} "
              f"proven={r3['proven']}  {time.time()-t:.0f}s", flush=True)
        proven_vals = [v for (v, pv) in [(v1, p1), (v2, p2)] if pv]
        if r3["proven"]:
            proven_vals.append(r3["blockA_lb"])
        if len(proven_vals) >= 2 and max(proven_vals) - min(proven_vals) < 0.5:
            print(f"  >>> AGREE: {proven_vals}  (independent confirmation)", flush=True)
        else:
            print(f"  >>> proven vals: {proven_vals}  -- inspect", flush=True)
