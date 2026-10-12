"""
D3 -- broaden K's satellite-proximity study (their Fig. 4) using the arithmetic bound.

K measure proximity at |C|=50 ONLY, from SOLUTIONS, and report averages:
    "the proximity scenario with value 0.1 optimizes the problems better on average in terms
     of fleet size and overall travel time compared to k-means"  (section 5.4)

WHAT A LOWER BOUND CAN AND CANNOT SAY -- the design of this sweep turns on it.

  * AB(prox=a) being LOWER than AB(prox=b) proves NOTHING. A lower bound can fall while the
    optimum rises; a loose bound at one setting is not evidence that setting is better.
  * AB(prox=a) EXCEEDING a known feasible objective at prox=b is a PROOF that b is strictly
    better than a on that cell, because AB(a) <= z*(a).

So the sweep is built one-directional on purpose: it can FALSIFY "higher proximity helps" per
cell, and can never confirm it. K's published per-instance BK at proximity 0 (Table 3, |C|=20
and 30) supplies the feasible objective. This yields a per-cell, provable statement where K had
only a per-average, solution-based observation at a single size -- a genuine broadening rather
than a restatement.

Writes runs/ab_proximity_sweep.json.
"""
import os, sys, json, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

from build_instance import build
from crossfeed.fullset_bound import fullset_bound
import lb_monitor as LM

CELLS = ([f"C2{i:02d}" for i in range(1, 9)] + [f"R2{i:02d}" for i in range(1, 12)]
         + [f"RC2{i:02d}" for i in range(1, 9)])
PROX = [0.0, 0.1, 0.2, 0.3, 0.4]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="20,30")
    a = ap.parse_args()
    out = []
    for size in [int(x) for x in a.sizes.split(",")]:
        kt = LM.k_table3(size)
        for cell in CELLS:
            row = {"cell": cell, "size": size,
                   "k_bk_prox0": (kt.get(cell) or (None, None, None))[2], "ab": {}}
            for pr in PROX:
                p = build(cell, size, wls=0.1, tau="formula", proximity=pr, time_limit=60)
                b, parts = fullset_bound(p)
                row["ab"][str(pr)] = {"bound": round(b, 3), "V_LB": parts["V_LB"],
                                      "dist": parts["dist_raw"], "water": parts["water"],
                                      "clique_used": parts["clique_used"],
                                      "triangle_excess": parts["triangle_excess"]}
            bk = row["k_bk_prox0"]
            # PROOF direction only: AB(prox=a) > BK(prox=0)  =>  prox 0 strictly beats prox a.
            row["dominated"] = ([pr for pr in PROX[1:]
                                 if bk and row["ab"][str(pr)]["bound"] > bk + 1e-6]
                                if bk else [])
            out.append(row)
            dom = row["dominated"]
            print(f"{cell:7} n{size}: " +
                  "  ".join(f"p{pr}={row['ab'][str(pr)]['bound']:8.2f}" for pr in PROX) +
                  f"   BK(p0)={bk if bk else '-'}" +
                  (f"   PROX {dom} PROVABLY WORSE THAN 0" if dom else ""), flush=True)
    json.dump(stamped(out, __file__), open(os.path.join(ROOT, "runs", "ab_proximity_sweep.json"), "w"), indent=1)

    print("\n" + "=" * 72)
    for size in sorted({r["size"] for r in out}):
        rs = [r for r in out if r["size"] == size]
        withbk = [r for r in rs if r["k_bk_prox0"]]
        print(f"\n|C|={size}, {len(withbk)} cells with a published BK at proximity 0:")
        for pr in PROX[1:]:
            d = [r["cell"] for r in withbk if pr in r["dominated"]]
            print(f"  proximity {pr}: PROVABLY worse than 0 on {len(d):2}/{len(withbk)} cells"
                  + (f"  {d}" if d and len(d) <= 8 else ""))
        # descriptive only -- explicitly NOT evidence about which proximity is better
        print("  (descriptive, NOT evidence of which proximity is better -- mean AB by prox)")
        for pr in PROX:
            m = sum(r["ab"][str(pr)]["bound"] for r in rs) / len(rs)
            nm = sum(1 for r in rs if not r["ab"][str(pr)]["clique_used"])
            print(f"    prox {pr}: mean AB {m:9.2f}   clique dropped (non-metric) on {nm}/{len(rs)}")


if __name__ == "__main__":
    main()
