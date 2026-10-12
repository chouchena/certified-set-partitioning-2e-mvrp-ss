"""Comprehensive cross-size report for the frzdual2 dual leg: our {LB, OV, RT} vs K {LB, best-OV, RT}
across n10/20/30/50/100, with per-cell OV parity (n10/20/30), the proven-optimum gold-standard check,
the proven/unproven split, and the 'less competitive as n decreases' prediction score.

K granularity: n10/20/30 = Table 3 (per-instance: joint_bk, joint_gap, lbbd_bk, lbbd_imp);
n50 = Table 4 (pooled, wls 1:10); n100 = Table 6 (per-family). PROXIMITY: 0.0 for n<=50, 0.1 for n100.
K_best = min(joint_bk, lbbd_bk) (K's better incumbent). K_LB = joint_bk*(1-joint_gap/100) (the only
published K LB = Joint-MILP Gurobi bound, d668). A cell is K-PROVEN iff joint_gap ~ 0.
Run SINGLE-TENANT. All our numbers from banked frzdual2 records.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import k_comparison as K

CELLS = (["C2%02d" % i for i in range(1, 9)] + ["R2%02d" % i for i in range(1, 12)]
         + ["RC2%02d" % i for i in range(1, 9)])
FAMN = {"C": 8, "R": 11, "RC": 8}
ATOL = 0.5


def ours(cell, size):
    p = os.path.join(ROOT, "runs", "oracle", "tep_solve_frzdual2_%s_n%d.json" % (cell, size))
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding="utf-8")); r = d.get("rows", [d]); r = r[0] if isinstance(r, list) else r
    rt = d.get("_rt") or {}
    return {"lb": r.get("lb"), "ov": r.get("ov"), "wall": rt.get("wall_s") or r.get("wall_s")}


def k_t3(cell, size):
    rec = K._kref()["table3"]["per_instance"].get(str(size), {}).get(cell)
    if not rec:
        return None
    jb, jg, lb = rec.get("joint_bk"), rec.get("joint_gap"), rec.get("lbbd_bk")
    best = min(x for x in (jb, lb) if x is not None)
    return {"best": best, "k_lb": jb * (1.0 - (jg or 0.0) / 100.0), "proven": (jg is not None and jg <= 0.05)}


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def per_cell_parity(size):
    rows = []
    for c in CELLS:
        o, k = ours(c, size), k_t3(c, size)
        if o and k and o["ov"] is not None:
            rows.append((c, o["ov"], o["lb"], k["best"], k["k_lb"], k["proven"]))
    return rows


def main(argv):
    print("=" * 96)
    print("CROSS-SIZE  frzdual2 dual  |  our {LB,OV,RT}  vs  K {LB, best-OV, RT}")
    print("=" * 96)
    print("  %-5s %-5s | %8s %8s %6s | %8s %8s %7s | %6s %6s %6s"
          % ("size", "prox", "ourLB", "ourOV", "ourRT", "K_LB", "K_best", "K_RT", "LBvsK", "OVvsK", "gap%"))
    # n10/20/30 pooled from Table 3 per-cell; n50 Table 4; n100 Table 6
    for size in (10, 20, 30):
        pc = per_cell_parity(size)
        if not pc:
            print("  n%-4d  0.0  | (no records)" % size); continue
        olb, oov, ort = mean([r[2] for r in pc]), mean([r[1] for r in pc]), mean([ours(r[0], size)["wall"] for r in pc])
        klb, kbest = mean([r[4] for r in pc]), mean([r[3] for r in pc])
        print("  n%-4d  0.0  | %8.1f %8.1f %6.0fs | %8.1f %8.1f %7s | %+5.0f%% %+5.0f%% %5.1f"
              % (size, olb, oov, ort, klb, kbest, "t.l.", 100*(olb/klb-1), 100*(oov/kbest-1), 100*(oov-olb)/olb))
    # n50
    o50 = [ours(c, 50) for c in CELLS]; o50 = [x for x in o50 if x]
    if o50:
        olb, oov, ort = mean([x["lb"] for x in o50]), mean([x["ov"] for x in o50]), mean([x["wall"] for x in o50])
        print("  n%-4d  0.0  | %8.1f %8.1f %6.0fs | %8.1f %8.1f %7s | %+5.0f%% %+5.0f%% %5.1f"
              % (50, olb, oov, ort, 835.5, 1941.8, "5107s", 100*(olb/835.5-1), 100*(oov/1941.8-1), 100*(oov-olb)/olb))
    # n100 (Table 6 family -> 27-cell weighted pooled)
    o100 = [ours(c, 100) for c in CELLS]; o100 = [x for x in o100 if x]
    t6 = K._kref()["table6"]
    kbest100 = sum(FAMN[f]*min(t6[f]["joint"]["zIP"], t6[f]["lbbd"]["zIP"]) for f in FAMN)/27
    klb100 = sum(FAMN[f]*t6[f]["joint"]["zIP"]*(1-t6[f]["gap_joint"]/100) for f in FAMN)/27
    if o100:
        olb, oov, ort = mean([x["lb"] for x in o100]), mean([x["ov"] for x in o100]), mean([x["wall"] for x in o100])
        print("  n%-4d  0.1  | %8.1f %8.1f %6.0fs | %8.1f %8.1f %7s | %+5.0f%% %+5.0f%% %5.1f"
              % (100, olb, oov, ort, klb100, kbest100, "14400s", 100*(olb/klb100-1), 100*(oov/kbest100-1), 100*(oov-olb)/olb))

    print("\n" + "=" * 96)
    print("PER-CELL OV PARITY (n10/20/30, vs K Table-3) + GOLD-STANDARD CHECK")
    print("=" * 96)
    for size in (10, 20, 30):
        pc = per_cell_parity(size)
        if not pc:
            continue
        nprov = sum(1 for r in pc if r[5])
        viol = [r[0] for r in pc if r[5] and r[1] < r[3] - ATOL]      # OV below a PROVEN optimum = bug
        exact = sum(1 for r in pc if abs(r[1] - r[3]) <= ATOL)
        beat = sum(1 for r in pc if r[1] < r[3] - ATOL)              # OV below K_best (unproven cells: legit)
        margins = sorted(100*(r[1]/r[3]-1) for r in pc)
        med = margins[len(margins)//2]
        print("  n%-3d  cells=%2d  K-proven=%2d | exact-match=%2d  beat-K=%2d  median OVvsK=%+5.2f%%  | PROVEN-OPT VIOLATIONS: %s"
              % (size, len(pc), nprov, exact, beat, med, (",".join(viol) if viol else "NONE")))
    print("  (a violation = our verified OV strictly below a cell K PROVED optimal -> impossible -> would be a bug)")

    print("\n" + "=" * 96)
    print("PREDICTION (author d664): dual-derived OV LESS competitive as n DECREASES")
    print("=" * 96)
    print("  OVvsK by size (prox 0.0): n10/20/30 from Table-3 per-cell median; n50 pooled; n100 @0.1 family-pooled")
    for size in (10, 20, 30):
        pc = per_cell_parity(size)
        if pc:
            margins = sorted(100*(r[1]/r[3]-1) for r in pc)
            print("    n%-3d  median OVvsK = %+6.2f%%" % (size, margins[len(margins)//2]))
    if o50:
        print("    n50   pooled OVvsK = %+6.2f%%" % (100*(mean([x['ov'] for x in o50])/1941.8-1)))
    if o100:
        print("    n100  pooled OVvsK = %+6.2f%%  (prox 0.1 -- separate regime)" % (100*(mean([x['ov'] for x in o100])/kbest100-1)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
