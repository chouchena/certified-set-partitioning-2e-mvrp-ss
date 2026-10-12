"""How much smaller than |C| can kappa legitimately be? A closed-form scan, no solve.

    python analysis/kappa_probe.py --sizes 20,30,50,100

WHY. The Lagrangian certificate is z_RMP + kappa * rc_min, where kappa must upper-bound the total
trip weight Sum_t lambda_t in an optimal LP solution. d430 took kappa = |C| ("each trip serves at
least one customer, so 100 is the honest bound") and recorded that the per-satellite spacing
argument gives 233, which is worse. Measured 2026-09-30, start-state pricing having driven the
pricer's residual slack to exactly 0, kappa is the ONLY thing left between this certificate and a
usable bound: at R211 n20 truncated to 8 iterations the exact reduced cost is -13.88 and kappa =
20 turns z_RMP 434.86 into 157.19, a sixth of the converged LP, where AB4 -- free -- gives 424.59.

THE ALTERNATIVE BOUND, and it needs no assumption beyond positive trip costs. Every trip column's
objective coefficient is c_t = tc * (D[L][first] + travel + D[last][p]) > 0, and in ANY feasible
solution Sum_t c_t lambda_t <= (that solution's street cost) <= z_RMP, because the restricted
master's value is an upper bound on the full LP's street part. With c_min = min over every
POSSIBLE trip of c_t,

    Sum_t lambda_t  <=  Sum_t (c_t / c_min) lambda_t  =  (1/c_min) Sum_t c_t lambda_t  <=  z_RMP / c_min.

c_min is a closed-form scan over (start node, customer, arrival node): the cheapest trip serves one
customer, so c_min = tc * min over L, c, p of (D[L][c] + D[c][p]). Nothing here is heuristic and
nothing needs the pricer. THIS SCRIPT ONLY MEASURES THE PRIZE -- whether z_RMP / c_min is materially
below |C| -- so that nobody spends a build on a factor that turns out to be 0.9 |C|.

WHAT IS NOT CLAIMED. The inequality above bounds the trip weight against the STREET part of the
objective; the master also carries the fleet variable N with its penalty, which only adds to
z_RMP, so using z_RMP whole is conservative in the safe direction. Whether the tightened kappa
makes the certificate beat AB4 is a separate measurement, and the bar is in the ledger, not here.
"""
import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))


def cheapest_trip(M):
    """tc * min over (start node, customer, arrival node) of D[L][c] + D[c][p], and its witness.

    Start nodes are the depot and every satellite; arrival nodes are the satellites (a trip ends
    at the satellite it hands its load to). Time windows are ignored ON PURPOSE: dropping them
    can only make the minimum smaller, so the resulting kappa stays valid.
    """
    D, tc = M.D, M.tc
    starts = [M.g] + list(M.sats)
    ends = list(M.sats)
    best = None
    for c in M.C:
        for L in starts:
            for p in ends:
                v = D[L][c] + D[c][p]
                if best is None or v < best[0]:
                    best = (v, L, c, p)
    return tc * best[0], best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="20,50")
    ap.add_argument("--cells", default=None, help="default: one cell per family")
    ap.add_argument("--delta", type=float, default=None)
    a = ap.parse_args()

    import tep_cg_bound as T
    import verifier3 as V
    from k_comparison import k_proximity
    from bound_certificate import certified, ng_certified
    from best_known import bound_artifacts

    cells = a.cells.split(",") if a.cells else ["R211", "C205", "RC206", "R204", "C204", "RC204"]
    print("%-6s %5s %5s %10s %10s %9s %9s  %s"
          % ("cell", "size", "|C|", "c_min", "banked LP", "kappa_new", "vs |C|", "witness (L -> c -> p)"))
    rows = []
    for size in [int(x) for x in a.sizes.split(",")]:
        for cell in cells:
            prox = k_proximity(size)
            try:
                inst = V.load_instance(cell, size, prox)
            except Exception as e:
                print("  %-6s n%-4d load failed: %s" % (cell, size, e)); continue
            delta = a.delta or T.default_delta(inst)
            M = T.Master(inst, delta, threads=1)
            cmin, wit = cheapest_trip(M)
            lp = None
            for p, d in bound_artifacts(cell, size):
                if "_primal" in os.path.basename(p) or d.get("primal_rounding") or d.get("drop"):
                    continue
                if d.get("lp_street") is None or not (certified(d) or ng_certified(d)):
                    continue
                v = float(d["lp_street"])
                lp = v if lp is None else max(lp, v)
            kap = (lp / cmin) if (lp and cmin > 0) else None
            n = len(M.C)
            rows.append(dict(cell=cell, size=size, n_customers=n, c_min=cmin, banked_lp=lp,
                             kappa_new=kap, kappa_old=n,
                             ratio=(kap / n if kap else None),
                             witness=dict(start=str(wit[1]), customer=str(wit[2]), end=str(wit[3]),
                                          distance=wit[0])))
            print("%-6s %5d %5d %10.3f %10s %9s %9s  %s -> %s -> %s"
                  % (cell, size, n, cmin, ("%.2f" % lp) if lp else "none",
                     ("%.1f" % kap) if kap else "-",
                     ("%.2fx" % (kap / n)) if kap else "-", wit[1], wit[2], wit[3]))
    os.makedirs(os.path.join(ROOT, "logs", "smoke"), exist_ok=True)
    p = os.path.join(ROOT, "logs", "smoke", "kappa_probe.json")
    json.dump(dict(rows=rows, note="kappa_new = banked street LP / cheapest possible trip cost; "
                                   "valid upper bound on the total trip weight, see the docstring"),
              io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    good = [r for r in rows if r["ratio"] is not None]
    if good:
        print("\nkappa_new / |C|: median %.2fx over %d cells; best %.2fx, worst %.2fx"
              % (sorted(r["ratio"] for r in good)[len(good) // 2], len(good),
                 min(r["ratio"] for r in good), max(r["ratio"] for r in good)))
    print("wrote %s  (no artifact under runs/: this measures a prize, it does not bound anything yet)"
          % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
