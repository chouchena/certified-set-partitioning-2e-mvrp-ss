"""BLIND vs COST-AWARE construction across the WHOLE GRID, with a self-vs-verifier OV check.

SCOPE IS THE GRID, NOT n20. Decision 27: no question here is scope-limited to |C| = 20 unless
there is a stated reason it cannot run wider. This covers 10/20/30/50/100, all 27 cells each.

TWO QUESTIONS, ANSWERED TOGETHER.

 1. Does cost-aware construction beat the blind rule, measured by the VERIFIER?
    BLIND  = successor_tries 1, the original rule: after a forced transfer it commits to the
             single nearest unvisited customer and ends the route if that one customer's
             deadline fails.
    AWARE  = a portfolio over successor_tries (1,3,5), keeping the best VERIFIED result.
             A portfolio and not a replacement because raising the parameter buys objective and
             pays coverage, and the payment falls on the C family.
    PAIRED on seeds, because `ov-corpus-cannot-select-variant` is standing: seed noise exceeds
    between-variant differences, so a best-of table would look the same and mean nothing.

 2. Does the constructor's OWN cost evaluation agree with the verifier's?
    The engine now computes `selfObjVal` beside `objVal`, which stays None. If the constructor
    miscalculates its own objective it can misdirect its own trajectory, so the two are compared
    on every single construction, not sampled. The trap is that a street arc leaving a TRANSFER
    customer costs D[i][hub] + D[hub][j], not D[i][j] -- and every route this constructor builds
    ends in a transfer, so getting that wrong would understate every route.

WHAT THIS IS NOT. Not a comparison with K, and none may be drawn from it. The greedy is multiples
away from our own best-known solutions at every size. This is one constructor against another on
identical seeds, with an internal consistency check alongside.

Usage:  python analysis/greedy_blind_vs_aware_grid.py --sizes 10,20,30,50,100 --seeds 5
"""
import argparse, collections, json, os, random, statistics as st, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from analysis.stamp import stamped
from solver.config import InstanceSpec                       # noqa: E402
from solver.problem import SolverProblem                     # noqa: E402
from solver.engines.construct import ConstructivePrimal      # noqa: E402
import analysis.manuscript_numbers as M                      # noqa: E402

LADDER = (1, 3, 5)


def fam(c):
    return "RC" if c.startswith("RC") else c[0]


def one(sp, tries, seed, hub_congestion):
    """One construction -> dict. Records VESSELS and TRANSFERS too, so the OV improvement can be
    decomposed into its fleet and routing parts rather than reported only as a percentage.

    z = nCars*penaltyCars + nVessel*penaltyVessels + c_s*street + c_w*water, so with cars and
    vessels in hand the residual IS the travel cost and no separate distance accounting is needed.
    """
    sol = ConstructivePrimal(singleton_vessels=True, successor_tries=tries,
                             hub_congestion=hub_congestion).construct(sp, random.Random(seed))
    if sol is None:
        return dict(obj=None, self=None, cars=None, ves=None, tr=None, ok=False)
    vd = sp.verify(sol)
    return dict(obj=getattr(vd, "recomputed_obj", None), self=sol.get("selfObjVal"),
                cars=sol.get("nCars"), ves=sol.get("nVessel"),
                tr=len(sol.get("vi") or []), ok=bool(vd.ok))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="10,20,30,50,100")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--hub-congestion", type=float, default=1.0,
                    help="1.0 matches the banked n100 B0 census")
    ap.add_argument("--out", default="runs/greedy_blind_vs_aware_grid.json")
    a = ap.parse_args()
    sizes = [int(x) for x in a.sizes.split(",")]

    print("BLIND vs COST-AWARE construction, paired on seeds, hub_congestion=%.1f" % a.hub_congestion)
    print("  BLIND = successor_tries 1     AWARE = best verified over successor_tries %s"
          % (LADDER,))
    print("  every objective below is the VERIFIER's independent recomputation\n")

    allrows, t0 = [], time.time()
    selfdiffs, selfnone, selfn = [], 0, 0

    for size in sizes:
        cells = sorted(M._cells(size))
        for c in cells:
            sp = SolverProblem(InstanceSpec.for_k_comparison(c, size))
            rw = sp.raw
            rec = dict(cell=c, size=size, fam=fam(c),
                       penCars=rw.penaltyCars, penVes=rw.penaltyVessels, seeds=[])
            for s in range(a.seeds):
                per = {}
                for t in LADDER:
                    r = one(sp, t, s, a.hub_congestion)
                    per[t] = r
                    if r["ok"] and r["obj"] is not None:
                        selfn += 1
                        if r["self"] is None:
                            selfnone += 1
                        else:
                            selfdiffs.append(abs(r["self"] - r["obj"]))
                rec["seeds"].append({str(k): v for k, v in per.items()})
            allrows.append(rec)
        # flush: without it nothing reaches a redirected log until the run ends, and a
        # spool-check minutes after launch cannot tell "working" from "hung".
        print("  n%-4d done (%.0fs elapsed)" % (size, time.time() - t0), flush=True)

    # ---------------- per-size summary -------------------------------------------------
    print("\n=== BLIND vs AWARE, by size. Paired per seed; negative d%% favours AWARE ===")
    print("%-6s %8s %8s %10s %10s %9s %9s %9s" %
          ("size", "cellsB", "cellsA", "seedsB%", "seedsA%", "mean d%", "median d%", "cars"))
    summary = {}
    for size in sizes:
        rs = [r for r in allrows if r["size"] == size]
        covB = covA = 0
        okB = okA = 0
        dl, carss = [], 0
        for r in rs:
            anyB = anyA = False
            for sd in r["seeds"]:
                b = sd["1"]
                cand = [(v["obj"], v["cars"]) for v in sd.values() if v["ok"] and v["obj"]]
                if b["ok"] and b["obj"]:
                    okB += 1; anyB = True
                if cand:
                    okA += 1; anyA = True
                if b["ok"] and b["obj"] and cand:
                    bo, bc = min(cand)
                    dl.append(100.0 * (bo - b["obj"]) / b["obj"])
                    carss += b["cars"] - bc
            covB += anyB; covA += anyA
        tot = len(rs) * a.seeds
        summary[size] = dict(cells=len(rs), covB=covB, covA=covA, okB=okB, okA=okA,
                             mean_d=st.mean(dl) if dl else None,
                             median_d=st.median(dl) if dl else None,
                             cars_saved=carss, pairs=len(dl))
        s = summary[size]
        print("%-6d %8s %8s %9.0f%% %9.0f%% %8.2f%% %8.2f%% %9d" %
              (size, "%d/%d" % (covB, len(rs)), "%d/%d" % (covA, len(rs)),
               100.0 * okB / tot, 100.0 * okA / tot,
               s["mean_d"], s["median_d"], carss))

    # ---------------- by family, since the cost falls on one -----------------------------
    print("\n=== AWARE vs BLIND by family (mean d%%, and coverage change) ===")
    print("%-6s %10s %10s %10s" % ("size", "C", "R", "RC"))
    for size in sizes:
        out = []
        for f in ("C", "R", "RC"):
            rs = [r for r in allrows if r["size"] == size and r["fam"] == f]
            dl = []
            for r in rs:
                for sd in r["seeds"]:
                    b = sd["1"]
                    cand = [v["obj"] for v in sd.values() if v["ok"] and v["obj"]]
                    if b["ok"] and b["obj"] and cand:
                        dl.append(100.0 * (min(cand) - b["obj"]) / b["obj"])
            out.append("%9.2f%%" % st.mean(dl) if dl else "        -")
        print("%-6d %10s %10s %10s" % (size, *out))

    # ---------------- the self-vs-verifier check ----------------------------------------
    print("\n=== CONSTRUCTOR'S OWN OV vs THE VERIFIER'S -- every verified construction ===")
    print("  constructions checked : %d" % selfn)
    print("  selfObjVal missing    : %d" % selfnone)
    if selfdiffs:
        print("  max |self - verifier| : %.9f" % max(selfdiffs))
        print("  mean |self - verifier|: %.9f" % st.mean(selfdiffs))
        over = sum(1 for d in selfdiffs if d > 1e-6)
        print("  disagreements > 1e-6  : %d of %d" % (over, len(selfdiffs)))
        if over:
            print("  !! THE CONSTRUCTOR MISCALCULATES ITS OWN OBJECTIVE. Any decision it makes")
            print("     using that number is misdirected. Fix before using selfObjVal anywhere.")
        else:
            print("  -> the constructor's own cost model AGREES with the independent verifier")
            print("     on every verified construction at every size. selfObjVal is safe to use")
            print("     for internal decisions; `objVal` still stays None by design, because the")
            print("     verifier's recomputation is the stronger provenance.")

    json.dump(stamped(dict(sizes=sizes, seeds=a.seeds, ladder=list(LADDER),
                   hub_congestion=a.hub_congestion,
                   summary={str(k): v for k, v in summary.items()},
                   self_check=dict(n=selfn, missing=selfnone,
                                   max_abs=max(selfdiffs) if selfdiffs else None,
                                   over_tol=sum(1 for d in selfdiffs if d > 1e-6)),
                   rows=allrows), __file__),
              open(os.path.join(ROOT, a.out), "w"), indent=1)
    print("\n  NOT a comparison with K. One constructor against another on identical seeds.")
    print("wrote %s  (%.0fs)" % (a.out, time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
