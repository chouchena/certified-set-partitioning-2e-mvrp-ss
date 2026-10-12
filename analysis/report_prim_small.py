"""Validate the PRIMAL leg at n10/20/30 against K's per-cell PROVEN optima (Table 3).

For each cell: K_opt (joint_bk where joint_gap~0), the dual BYPRODUCT OV (frzdual2), and each primal
variant's OV (prim2_P0/P-sel/P-alns/P-full). Answers:
  * does the primal REACH K's proven optimum (within tol)? which variant?
  * does it FIX the erratic byproduct cells (d669) -- i.e. best primal << byproduct where byproduct was off?
  * GOLD-STANDARD: no variant OV strictly below a proven optimum (would be a bug).
  * per-cell gap-to-our-LB (the dual's certified LB), the secondary diagnostic.
Run SINGLE-TENANT after the primal run exits.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import k_comparison as K

CELLS = (["C2%02d" % i for i in range(1, 9)] + ["R2%02d" % i for i in range(1, 12)]
         + ["RC2%02d" % i for i in range(1, 9)])
VARIANTS = ["P0", "P-sel", "P-alns", "P-full"]
RELTOL = 0.005   # within 0.5% of optimum counts as "reached"
ABSTOL = 0.5


def ov(tag, cell, size):
    p = os.path.join(ROOT, "runs", "oracle", "tep_solve_%s_%s_n%d.json" % (tag, cell, size))
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding="utf-8")); r = d.get("rows", [d]); r = r[0] if isinstance(r, list) else r
    return r.get("ov")


def dual(cell, size):
    p = os.path.join(ROOT, "runs", "oracle", "tep_solve_frzdual2_%s_n%d.json" % (cell, size))
    if not os.path.exists(p):
        return None, None
    d = json.load(open(p, encoding="utf-8")); r = d.get("rows", [d]); r = r[0] if isinstance(r, list) else r
    return r.get("ov"), r.get("lb")


def main(argv):
    for size in (10, 20, 30):
        pi = K._kref()["table3"]["per_instance"].get(str(size), {})
        print("\n" + "=" * 92)
        print("PRIMAL vs K PROVEN OPTIMA | n%d" % size)
        print("=" * 92)
        reached = {v: 0 for v in VARIANTS}; reached["best"] = 0
        viol = []; fixed = []; n = 0; notreached = []
        for c in CELLS:
            k = pi.get(c, {}); kopt = k.get("joint_bk"); proven = (k.get("joint_gap") is not None and k["joint_gap"] <= 0.05)
            bov, blb = dual(c, size)
            vs = {v: ov("prim2_%s" % v, c, size) for v in VARIANTS}
            have = [x for x in vs.values() if x is not None]
            if kopt is None or not have:
                continue
            n += 1
            best = min(have)
            for v in VARIANTS:
                if vs[v] is not None and vs[v] <= kopt * (1 + RELTOL):
                    reached[v] += 1
            if best <= kopt * (1 + RELTOL):
                reached["best"] += 1
            else:
                notreached.append((c, best, kopt, 100 * (best / kopt - 1)))
            if proven:
                for v in VARIANTS:
                    if vs[v] is not None and vs[v] < kopt - ABSTOL:
                        viol.append("%s/%s" % (c, v))
            # did the primal fix an erratic byproduct cell? byproduct off (>2% over opt) but best primal reaches
            if bov is not None and bov > kopt * 1.02 and best <= kopt * (1 + RELTOL):
                fixed.append((c, bov, best, kopt))
        print("  cells=%d | reached-optimum (within %.1f%%):  P0=%d  P-sel=%d  P-alns=%d  P-full=%d  | ANY=%d"
              % (n, 100 * RELTOL, reached["P0"], reached["P-sel"], reached["P-alns"], reached["P-full"], reached["best"]))
        print("  PROVEN-OPTIMUM VIOLATIONS (OV below a proven optimum -> bug): %s" % (",".join(viol) if viol else "NONE"))
        if fixed:
            print("  FIXED erratic byproduct cells (byproduct off -> primal reaches optimum):")
            for c, b, p, o in fixed:
                print("     %-6s byproduct %.1f (+%.1f%%)  ->  primal %.1f  (opt %.1f)" % (c, b, 100*(b/o-1), p, o))
        if notreached:
            print("  NOT reaching optimum (best primal vs opt):")
            for c, b, o, g in sorted(notreached, key=lambda t: -t[3]):
                print("     %-6s best %.1f  opt %.1f  (+%.1f%%)" % (c, b, o, g))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
