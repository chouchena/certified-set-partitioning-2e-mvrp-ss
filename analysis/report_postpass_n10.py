"""Which EXISTING path (postpass corpus) reaches each n10 cell's optimum? For each cell: the dual
own-water incumbent (ownwater, = the frozen dual OV path), the ceil-arm, and the cars-first
select-chain -- vs K's proven optimum (table3). Shows whether a single path (e.g. select-chain)
closes the big n10 gaps the frozen dual/primal leaves open (fleet-basin: 1-car vs 2-car).
Read-only, single-tenant. (Corpus is cross-config best-of -> informative ceiling, not citable;
d651. Use it to PICK the variant, then clean-rerun + scale.)
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import k_comparison as K

CELLS = (["C2%02d" % i for i in range(1, 9)] + ["R2%02d" % i for i in range(1, 12)]
         + ["RC2%02d" % i for i in range(1, 9)])
PATHS = ["", "ceil", "selchain", "refine", "alns"]   # "" = ownwater (dual own-water incumbent)


def ov_cars(sub, cell, size):
    p = os.path.join(ROOT, "runs", "postpass", sub, "ownwater_%s_n%d.json" % (cell, size))
    if not os.path.exists(p):
        return None, None
    d = json.load(open(p, encoding="utf-8"))
    return d.get("objVal"), d.get("nCars")


def main(argv):
    size = int(argv[1]) if len(argv) > 1 else 10
    pi = K._kref()["table3"]["per_instance"].get(str(size), {})
    print("=== postpass paths vs K proven optimum | n%d ===" % size)
    print("  %-6s %8s | %8s %8s %8s %8s %8s | %8s %7s  %s"
          % ("cell", "Kopt", "dual", "ceil", "selchn", "refine", "alns", "BEST", "vs opt", "winner"))
    nreach = 0; n = 0; sel_reach = 0; sel_n = 0
    for c in CELLS:
        kopt = pi.get(c, {}).get("joint_bk")
        if kopt is None:
            continue
        vals = {}
        for sub in PATHS:
            ov, cars = ov_cars(sub, c, size)
            vals[sub or "dual"] = ov
        have = {k: v for k, v in vals.items() if v is not None}
        if not have:
            continue
        n += 1
        best_k = min(have, key=have.get); best = have[best_k]
        reach = best <= kopt * 1.01
        if reach:
            nreach += 1
        if vals.get("selchain") is not None:
            sel_n += 1
            if vals["selchain"] <= kopt * 1.01:
                sel_reach += 1
        def f(x):
            return ("%.1f" % x) if x is not None else "-"
        print("  %-6s %8.1f | %8s %8s %8s %8s %8s | %8.1f %+6.1f%%  %s"
              % (c, kopt, f(vals.get("dual")), f(vals.get("ceil")), f(vals.get("selchain")),
                 f(vals.get("refine")), f(vals.get("alns")), best, 100*(best/kopt-1), best_k))
    print("\n  BEST-of-paths reaches optimum (<=1%%): %d / %d" % (nreach, n))
    print("  SELECT-CHAIN alone reaches optimum:    %d / %d" % (sel_reach, sel_n))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
