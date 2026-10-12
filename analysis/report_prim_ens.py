"""Ensemble primal variant (prim_ens, d674) vs K proven optima at n10 -- the single-run, clean-config
result (NOT cross-config best-of). Per cell: prim_ens OV/LB/gap, K opt, reach?; summary vs the prim2
baseline (17/27) and the postpass corpus ceiling (25/27). Shows how much ONE citable pipeline closes.
Run single-tenant after prim_ens completes (or any time -- read-only, shows progress).
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import k_comparison as K

CELLS = (["C2%02d" % i for i in range(1, 9)] + ["R2%02d" % i for i in range(1, 12)]
         + ["RC2%02d" % i for i in range(1, 9)])


def rec(tag, cell, size):
    p = os.path.join(ROOT, "runs", "oracle", "tep_solve_%s_%s_n%d.json" % (tag, cell, size))
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding="utf-8")); r = d.get("rows", [d]); r = r[0] if isinstance(r, list) else r
    return r


def main(argv):
    size = int(argv[1]) if len(argv) > 1 else 10
    pi = K._kref()["table3"]["per_instance"].get(str(size), {})
    print("=== ENSEMBLE PRIMAL (prim_ens) vs K optima/best | n%d ===" % size)
    print("  %-6s %8s %8s %6s | %8s %7s %7s  %s"
          % ("cell", "ourOV", "ourLB", "gap%", "Kopt", "OVvsopt", "reach?", "stages"))
    n = reach = 0
    for c in CELLS:
        r = rec("prim_ens", c, size)
        kopt = pi.get(c, {}).get("joint_bk")
        if r is None or kopt is None or r.get("ov") is None:
            continue
        n += 1
        ov = r["ov"]; lb = r.get("lb")
        rr = ov <= kopt * 1.01
        if rr:
            reach += 1
        gap = (100.0 * (ov - lb) / lb) if lb else None
        print("  %-6s %8.2f %8s %6s | %8.1f %+6.1f%% %7s  %s"
              % (c, ov, ("%.1f" % lb) if lb else "-", ("%.1f" % gap) if gap is not None else "-",
                 kopt, 100 * (ov / kopt - 1), "YES" if rr else "no", (r.get("story") or "")[:40]))
    print("\n  prim_ens reaches optimum (<=1%%): %d / %d  (prim2 baseline 17/27; corpus best-of ceiling 25/27)" % (reach, n))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
