"""Can the TEP LP join AB4's PER-COMPONENT maximum instead of competing with it as a lump?

    python analysis/decomp_probe.py --sizes 10,20,30,50,100

THE IDEA (author, 2026-10-01): "define a maximization problem where OV is max LB ... constraints
are validity of LB". AB4 already is one -- crossfeed/fullset_bound.py bounds the street cost as
penaltyCars * V_LB + travelcoststreet * Dist_LB with V_LB = max(routes_lb_time, clique) and
Dist_LB = max over three relaxations. What it does NOT do is let the TEP master's LP compete
component by component: today the reported bound is max(lp_street + water, ab4), a choice
between two whole bounds, so a cell whose TEP LP has the better FLEET term but the worse TRAVEL
term loses the good half.

THE DECOMPOSITION. The master's objective is pen * N + tc * (street travel), so its LP value
splits exactly: fleet part = pen * N_LP, travel part = lp_street - pen * N_LP.

WHAT IS LICENSED AND WHAT IS NOT -- the validity constraint the formulation turns on.
  * pen * N_LP IS a valid fleet bound. d420 established that the LP is a relaxation whose car
    count bounds every feasible solution from below, which is exactly why the integer-car cut
    N >= ceil(N_LP) is sound. So N_LP <= V* and pen * N_LP <= pen * V*.
  * (lp_street - pen * N_LP) is NOT established as a valid travel bound. An LP optimum does not
    decompose into component-wise bounds: the LP may buy few cars and much travel while the
    optimum does the reverse, so the travel half can exceed travel*. Nothing here uses it.
Therefore the only admissible mixed bound is

    max(pen * N_LP, fleet_term_AB4) + travel_term_AB4 + water

and the reported value would be the max of THAT and the two existing candidates. It beats the
status quo exactly when the TEP LP's fleet half is the better fleet bound AND AB4's travel term
beats the TEP LP's travel half.

THIS SCRIPT ONLY MEASURES THE PRIZE. It writes no bound and changes no reader. If the gain is
zero the idea is closed for free; if it is material the mixed bound still needs the fleet
inequality written down properly before anything uses it.
"""
import argparse
import glob
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="10,20,30,50,100")
    a = ap.parse_args()
    from bound_certificate import certified, ng_certified
    from best_known import bound_artifacts
    from run_full_grid import all_cells
    import verifier3 as V
    from k_comparison import k_proximity

    ab = {(q["cell"], q["size"]): q for q in json.load(io.open(
        os.path.join(ROOT, "runs", "ab_grid_provenanced.json"), encoding="utf-8"))["records"]}
    print("%-6s %5s %9s %9s %11s %11s %11s %11s %9s  %s"
          % ("cell", "size", "pen", "N_LP", "TEP fleet", "AB4 fleet", "status quo", "mixed", "gain", "why"))
    tot = n = wins = 0
    for size in [int(x) for x in a.sizes.split(",")]:
        pen = float(V.load_instance(all_cells()[0], size, k_proximity(size)).penalty_cars)
        for cell in all_cells():
            q = ab.get((cell, size))
            if not q:
                continue
            best = None
            for p, d in bound_artifacts(cell, size):
                b = os.path.basename(p)
                if "_primal" in b or d.get("primal_rounding") or d.get("drop"):
                    continue
                if d.get("lp_street") is None or d.get("N") is None:
                    continue
                if not (certified(d) or ng_certified(d)):
                    continue
                if best is None or float(d["lp_street"]) > float(best["lp_street"]):
                    best = d
            if best is None:
                continue
            n += 1
            lp, nlp = float(best["lp_street"]), float(best["N"])
            w, f_ab, t_ab, ab4 = float(q["water"]), float(q["fleet_term"]), float(q["travel_term"]), float(q["ab4"])
            f_tep = pen * nlp
            status_quo = max(lp + w, ab4)
            mixed = max(f_tep, f_ab) + t_ab + w
            gain = mixed - status_quo
            if gain > 1e-6:
                wins += 1
                tot += gain
                print("%-6s %5d %9.2f %9.3f %11.2f %11.2f %11.4f %11.4f %9.4f  %s"
                      % (cell, size, pen, nlp, f_tep, f_ab, status_quo, mixed, gain,
                         "TEP fleet wins and AB4 travel beats the LP's travel half"))
    print("\ncells examined %d | cells where the mixed bound WINS %d | total gain %.4f" % (n, wins, tot))
    if not wins:
        print("the per-component mix never beats max(composed, ab4) on the banked grid:")
        print("  wherever the TEP LP's fleet half is the better fleet bound, its travel half")
        print("  already exceeds AB4's travel term, so the lump comparison loses nothing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
