"""Recompute FleetStreet / TravelStreet / FleetWater / TravelWater on every banked best-known. (d598)

WHY. The ceilings that gate the two most expensive operators need the cost split, and it is
recorded on only 22 of 135 banked best-knowns. `fix_routing` fixes xij, so street routes and nCars
are frozen and its maximum possible gain is the ENTIRE water cost -- a median 9.0 per cent of the
objective on the 22 cells where we can currently see it. Without the split on the other 113, that
trigger cannot be evaluated per cell.

It is a RECOMPUTE, not a re-run. verifier3 already derives every part in order to verify:
`run.objective` carries `street` and `water` travel distances and `n_cars`/`n_vessel`, and the
penalties and unit travel costs are instance constants. So:

    FleetStreet  = penalty_cars     * n_cars
    TravelStreet = travelcoststreet * street
    FleetWater   = penalty_vessels  * n_vessel
    TravelWater  = travelcostwater  * water

Nothing here re-implements the cost model; it reads the verifier's own decomposition. That is
deliberate -- a second cost model is exactly the duplicate-authority defect
`analysis/single_authority.py` exists to stop.

THE FALSIFIER, run before the recompute touches anything: 22 cells already carry all four
components. The recompute must reproduce all 22 to the cent. If it does not, the recompute is
wrong and the other 113 are not written.

    python analysis/tep_cost_decomposition.py --check     # falsifier only, writes nothing
    python analysis/tep_cost_decomposition.py             # falsifier, then recompute and write
"""
import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from best_known import best_solution
from k_comparison import k_proximity
from stamp import stamped

CELLS = (["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)]
         + ["RC%d" % i for i in range(201, 209)])
SIZES = (10, 20, 30, 50, 100)
PARTS = ("FleetStreet", "TravelStreet", "FleetWater", "TravelWater")
TOL = 0.01


def decompose(cell, size):
    """(parts dict, recomputed objective, claimed objective, artifact path) or None."""
    bs = best_solution(cell, size)
    if not bs:
        return None
    path = os.path.join(ROOT, bs[2])
    try:
        sol = json.load(io.open(path, encoding="utf-8"))
    except Exception:
        return None
    inst = V.load_instance(cell, size, k_proximity(size))
    run = V.verify_solution(inst, sol, cell=cell, size=size, proximity=k_proximity(size),
                            label="cost-decomposition")
    o = getattr(run, "objective", None)
    if not o:
        return None
    parts = {
        "FleetStreet": float(inst.penalty_cars) * o["n_cars"],
        "TravelStreet": float(inst.travelcoststreet) * o["street"],
        "FleetWater": float(inst.penalty_vessels) * o["n_vessel"],
        "TravelWater": float(inst.travelcostwater) * o["water"],
    }
    return parts, o["recomputed"], sol.get("objVal"), bs[2], sol


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="falsifier only; write nothing")
    a = ap.parse_args()

    print("COST DECOMPOSITION -- falsifier first, against the cells that already carry it\n")
    known, agree, bad = 0, 0, []
    results = {}
    for size in SIZES:
        for cell in CELLS:
            got = decompose(cell, size)
            if not got:
                continue
            parts, recomp, claimed, rel, sol = got
            results[(cell, size)] = (parts, recomp, claimed, rel)
            if all(sol.get(k) is not None for k in PARTS):
                known += 1
                diffs = {k: parts[k] - float(sol[k]) for k in PARTS}
                if all(abs(v) <= TOL for v in diffs.values()):
                    agree += 1
                else:
                    bad.append((cell, size, diffs))
    print("  cells already carrying all four parts: %d" % known)
    print("  of those, the recompute reproduces:    %d" % agree)
    if bad:
        print("\n  *** FALSIFIER FIRED -- the recompute disagrees on %d cell(s):" % len(bad))
        for cell, size, d in bad[:6]:
            print("      %-6s n%-4d %s" % (cell, size, {k: round(v, 3) for k, v in d.items()}))
        print("\n  Nothing written. The recompute is wrong and must be fixed before it is trusted.")
        return 1
    if known == 0:
        print("\n  *** NO CELL carries all four parts, so the recompute has NOTHING to validate against.")
        print("  That is not a pass. Refusing to write %d unvalidated decompositions." % len(results))
        return 1
    print("  falsifier passed: %d of %d reproduced to within %.2f\n" % (agree, known, TOL))

    print("  %-5s %7s %14s %14s %14s" % ("size", "cells", "water share med", "min", "max"))
    import statistics as st
    rows = []
    for size in SIZES:
        sh = []
        for cell in CELLS:
            if (cell, size) not in results:
                continue
            parts, recomp, claimed, rel = results[(cell, size)]
            tot = sum(parts.values())
            w = 100.0 * (parts["FleetWater"] + parts["TravelWater"]) / tot if tot else None
            if w is not None:
                sh.append(w)
            rows.append(dict(cell=cell, size=size, artifact=rel, recomputed=recomp,
                             claimed=claimed, water_share_pct=w, **parts))
        if sh:
            print("  n%-4d %7d %13.1f%% %13.1f%% %13.1f%%" % (size, len(sh), st.median(sh), min(sh), max(sh)))
    allsh = [r["water_share_pct"] for r in rows if r["water_share_pct"] is not None]
    print("\n  %d of 135 cells decomposed | fix_routing ceiling (= total water) median %.1f%%, max %.1f%%"
          % (len(rows), st.median(allsh), max(allsh)))
    if a.check:
        print("  --check: nothing written.")
        return 0
    p = os.path.join(ROOT, "runs", "oracle", "tep_cost_decomposition.json")
    json.dump(stamped(dict(rows=rows, tol=TOL, validated_against=known)),
              io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
