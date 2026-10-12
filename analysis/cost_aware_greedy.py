"""Does cost-aware construction beat the distance-only rule? A PAIRED design.

WHY PAIRED, AND WHY NOT BEST-OF. `ov-corpus-cannot-select-variant` is STANDING: seed noise on this
primal exceeds the between-variant difference, so any "variant X is better" claim needs a fresh
paired design and cannot be read off a best-of. This runs every arm on the SAME seeds and reports
the per-seed difference, which removes the seed as a source of variance instead of averaging over
it. A best-of table would have shown the same headline and meant nothing.

WHAT IS BEING COMPARED. `successor_tries`, in `feasible_construct.construct_feasible_decision`.

  st = 1  the original rule. After a forced transfer the constructor commits to the SINGLE
          nearest unvisited customer; if that one customer's deadline cannot be met, the route
          ends and a new car opens. It never tries the second-nearest.
  st > 1  try successors nearest-first and take the first that both admits a transfer and can be
          reached in time.

THE MIS-WEIGHTING THIS TARGETS, in the objective's own units. The verifier computes
    z = nCars*penaltyCars + nVessel*penaltyVessels + c_s*street + c_w*water
with c_s = 1, so raw street distance IS cost and the old key was already right for the travel
term. What it never carried is the fleet term: a car costs penaltyCars = 131-194 on these cells,
while the nearest and second-nearest successor differ by a few distance units. The old rule
refused a detour worth ~1 to accept a consequence worth ~145.

WHAT THIS IS NOT. It is not a comparison with K, and no such comparison may be drawn from it --
the greedy remains multiples away from our own best-known solutions, let alone K's. This measures
one constructor against another constructor on identical seeds. `w_deadend` and `w_urgency` are
also available but measured near-inert at |C| = 20 and are not the subject here.

Usage:  python analysis/cost_aware_greedy.py --size 20 --seeds 10 --arms 1,2,3,5
"""
import argparse, collections, json, os, random, statistics as st, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from analysis.stamp import stamped
from solver.config import InstanceSpec                       # noqa: E402
from solver.problem import SolverProblem                     # noqa: E402
from solver.engines.construct import ConstructivePrimal      # noqa: E402
import analysis.manuscript_numbers as M                      # noqa: E402


def fam(c):
    return "RC" if c.startswith("RC") else c[0]


def run(sp, tries, seed, hub_congestion=0.0):
    """One construction. Returns (obj, cars, ok) with obj from the VERIFIER, never claimed."""
    sol = ConstructivePrimal(singleton_vessels=True, successor_tries=tries,
                             hub_congestion=hub_congestion).construct(
        sp, random.Random(seed))
    if sol is None:
        return None, None, False
    vd = sp.verify(sol)
    return getattr(vd, "recomputed_obj", None), sol.get("nCars"), bool(vd.ok)


def construct_best_of(sp, seed, ladder=(1, 3, 5), hub_congestion=0.0):
    """THE RECOMMENDED WAY TO CALL THIS. Returns (solution, obj, cars, tries_used) or (None,)*4.

    A PORTFOLIO, NOT A REPLACEMENT, and the measurement is why. Raising `successor_tries` buys
    objective and pays COVERAGE, and the payment falls entirely on the C family: at |C| = 100 the
    C cells go 8 covered / 42% of seeds at st=1, to 6 / 25% at st=3, to 4 / 10% at st=5. The
    mechanism is the one already banked -- fewer cars means longer routes, which pushes transfers
    later into a horizon that tau = 180 already saturates.

    Run cheaply over the ladder and keep the best VERIFIED result and the arms stop being
    substitutes. Measured at |C| = 100, 27 cells, 5 seeds, hub_congestion 1.0:

        arm        cells covered   seed-level verified   mean d% vs st=1
        st=1            27                80%                  --
        st=3            25                73%               -7.10%
        st=5            23                64%               -9.07%
        PORTFOLIO       27                84%               -8.75%

    The portfolio beats EVERY single arm on both axes at once, including the baseline on
    feasibility -- when st=1 strands a seed, a longer ladder rung sometimes rescues it. The
    constructor costs well under a second per cell, so the ladder is close to free.

    Verification is the caller's job here because the engine sets objVal = None by design; every
    objective below is the verifier's own independent recomputation.
    """
    best = (None, None, None, None)
    for t in ladder:
        o, n, ok = None, None, False
        sol = ConstructivePrimal(singleton_vessels=True, successor_tries=t,
                                 hub_congestion=hub_congestion).construct(sp, random.Random(seed))
        if sol is not None:
            vd = sp.verify(sol)
            o, n, ok = getattr(vd, "recomputed_obj", None), sol.get("nCars"), bool(vd.ok)
        if ok and o is not None and (best[1] is None or o < best[1]):
            best = (sol, o, n, t)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--arms", default="1,2,3,5")
    ap.add_argument("--cells", default="")
    ap.add_argument("--hub-congestion", type=float, default=0.0,
                    help="match the banked n100 census, which used 1.0")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    arms = [int(x) for x in a.arms.split(",")]
    base = arms[0]
    if a.out is None:
        a.out = "runs/cost_aware_greedy_n%d.json" % a.size
    cells = ([c.strip() for c in a.cells.split(",") if c.strip()]
             or sorted(M._cells(a.size)))

    print("COST-AWARE CONSTRUCTION, paired on seeds. |C| = %d, %d cells, %d seeds, arms %s"
          % (a.size, len(cells), a.seeds, arms))
    print("baseline arm = successor_tries %d (the original nearest-only rule)\n" % base)
    print("%-7s %6s | %s" % ("cell", "fam",
                             " ".join("%18s" % ("st=%d  mean/cars" % t) for t in arms)))

    rows, t0 = [], time.time()
    for c in cells:
        # for_k_comparison, NOT the plain constructor: it is what greedy_coverage.py
        # uses, and at |C| = 100 it builds at K's table6 proximity 0.1 rather than the
        # 0.0 default. Without it the n100 numbers are not comparable with the banked
        # B0 census. The two coincide at |C| = 20, so the n20 arm is unaffected.
        sp = SolverProblem(InstanceSpec.for_k_comparison(c, a.size))
        per = {}
        for t in arms:
            objs, cars, oks = [], [], 0
            for s in range(a.seeds):
                o, n, ok = run(sp, t, s, a.hub_congestion)
                if ok and o:
                    objs.append(o); cars.append(n); oks += 1
            per[t] = dict(objs=objs, cars=cars, ok=oks)
        rows.append(dict(cell=c, size=a.size, fam=fam(c), arms={str(k): v for k, v in per.items()}))
        cells_txt = []
        for t in arms:
            p = per[t]
            cells_txt.append("%9.1f/%4.1f" % (st.mean(p["objs"]), st.mean(p["cars"]))
                             if p["objs"] else "     FAIL")
        print("%-7s %6s | %s" % (c, fam(c), " ".join("%18s" % x for x in cells_txt)))

    # ---- paired summary: per-seed difference against the baseline arm --------------------
    print("\n=== PAIRED against st=%d -- per-seed differences, not a best-of ===" % base)
    print("%-8s %8s %10s %10s %8s %8s %9s" %
          ("arm", "cells", "mean d%", "median d%", "better", "worse", "cars saved"))
    summary = {}
    for t in arms:
        if t == base:
            continue
        dpc, better, worse, carsd, n = [], 0, 0, [], 0
        for r in rows:
            b, x = r["arms"][str(base)], r["arms"][str(t)]
            k = min(len(b["objs"]), len(x["objs"]))
            if not k:
                continue
            n += 1
            for i in range(k):
                d = 100.0 * (x["objs"][i] - b["objs"][i]) / b["objs"][i]
                dpc.append(d)
                carsd.append(b["cars"][i] - x["cars"][i])
            mb, mx = st.mean(b["objs"][:k]), st.mean(x["objs"][:k])
            better += mx < mb - 1e-9
            worse += mx > mb + 1e-9
        summary[t] = dict(cells=n, mean_dpc=st.mean(dpc) if dpc else None,
                          median_dpc=st.median(dpc) if dpc else None,
                          better=better, worse=worse,
                          cars_saved=sum(carsd), pairs=len(dpc))
        s = summary[t]
        print("%-8s %8d %9.2f%% %9.2f%% %8d %8d %9d" %
              ("st=%d" % t, s["cells"], s["mean_dpc"], s["median_dpc"],
               s["better"], s["worse"], s["cars_saved"]))

    print("\n  d%% is (arm - baseline)/baseline per SEED; negative is better.")
    print("  'better'/'worse' count CELLS by their mean; they need not sum to the cell count.")
    print("  'cars saved' is the total over all cell-seed pairs -- the mechanism being targeted.")
    print("\n  NOT a comparison with K. The greedy is still multiples away from our own")
    print("  best-known solutions; this measures one constructor against another.")

    json.dump(stamped(dict(size=a.size, seeds=a.seeds, arms=arms, baseline=base,
                   rows=rows, summary={str(k): v for k, v in summary.items()}), __file__),
              open(os.path.join(ROOT, a.out), "w"), indent=1)
    print("\nwrote %s  (%.0fs)" % (a.out, time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
