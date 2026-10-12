"""Full n100 grid summary -- OUR fast-pricer frozen dual (frzdual2) vs K Table 6, at FAMILY-MEAN
granularity. This is the granularity that is CLAIMABLE at n100: K publishes no per-instance n100
data, only family means (C/R/RC), and our family mean is over the SAME instances (C201-208,
R201-211, RC201-208), so mean-to-mean is apples-to-apples on an identical instance set.

The dual leg's deliverable is the LOWER BOUND. The load-bearing comparison is therefore:
  our certified family-mean LB   vs   K's implied family-mean LB
where K's implied LB uses K's own reported gap: K_LB = zIP_joint * (1 - gap_joint/100).
(Same inversion as report_v2_cell.py; convention stated below so it cannot be read silently.)

Caveats printed, not hidden:
  * our OV is OUR solver's derived incumbent (verified feasible), not K's -- an OV family-mean
    comparison is suggestive, NOT a per-instance "we beat K" (that needs per-cell n100, unpublished).
  * a family mean mixes certified (ng) and any AB4-floored cells; n_certified is printed so a
    mixed family cannot masquerade as fully certified.
  * gap conventions may differ (ours (OV-LB)/LB; K's as published); the order-of-magnitude
    separation (ours ~15-25% vs K 60-77%) dominates any convention nuance, but both are shown raw.

Run SINGLE-TENANT (after the grid python has exited).
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))

FAMS = {
    "C": ["C2%02d" % i for i in range(1, 9)],
    "R": ["R2%02d" % i for i in range(1, 12)],
    "RC": ["RC2%02d" % i for i in range(1, 9)],
}


def _load(p):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def _row(d):
    r = d.get("rows", [d])
    return r[0] if isinstance(r, list) else r


def cell(c, size=100):
    d = _load(os.path.join(ROOT, "runs", "oracle", "tep_solve_frzdual2_%s_n%d.json" % (c, size)))
    if d is None:
        return None
    r = _row(d)
    rt = d.get("_rt") or {}
    return {"cell": c, "lb": r.get("lb"), "ov": r.get("ov"), "cert": r.get("certificate"),
            "wall_s": rt.get("wall_s") or r.get("wall_s"), "work": r.get("work")}


def kfam():
    import k_comparison as K
    t6 = K._kref()["table6"]
    out = {}
    for fam in ("C", "R", "RC"):
        row = t6[fam]
        zj = row["joint"]["zIP"]
        gap = row["gap_joint"]
        zl = (row.get("lbbd") or {}).get("zIP")            # K's LBBD incumbent (its better method at n100)
        k_inc = min([x for x in (zj, zl) if x is not None])  # K's published BEST OV = min(joint, lbbd)
        # K's implied LB from the joint gap (gap_lbbd is not published -> joint is the only computable LB)
        out[fam] = {"k_inc": k_inc, "k_joint": zj, "k_lbbd": zl, "k_gap": gap,
                    "k_lb": zj * (1.0 - gap / 100.0)}
    return out


def mean(xs):
    xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs)) if xs else None


def main(argv):
    size = int(argv[1]) if len(argv) > 1 else 100
    K = kfam()
    K_TL = 14400.0   # K per-cell TIME LIMIT (K-seconds); HIT at n100 (unsolved, 60-77% gap)
    HW = 2.5         # our-seconds = K-seconds / 2.5 (d245/d246/d250); 14400 K-s = 5760 our-s
    print("=== FULL n100 grid: frzdual2 family means | OUR LB/OV/RT  vs  K LB/best-OV/RT | n%d ===\n" % size)
    print("  %-4s %5s | %8s %8s %7s | %8s %8s %7s | %6s %6s %6s"
          % ("fam", "n/ng", "ourLB", "ourOV", "ourRT", "K_LB", "K_best", "K_RT", "LBvsK", "OVvsK", "gap%"))
    allcells = []
    for fam, cells in FAMS.items():
        rs = [x for x in (cell(c, size) for c in cells) if x]
        allcells += rs
        if not rs:
            print("  %-4s   --  (no frzdual2 records yet)" % fam)
            continue
        ncert = sum(1 for r in rs if r["cert"] == "ng")
        mlb = mean([r["lb"] for r in rs]); mov = mean([r["ov"] for r in rs])
        mrt = mean([r["wall_s"] for r in rs])
        ggap = 100.0 * (mov - mlb) / mlb if (mlb and mov) else None
        k = K[fam]
        lb_vs = ("%+.0f%%" % (100.0 * (mlb / k["k_lb"] - 1.0))) if (mlb and k["k_lb"]) else "n/a"
        ov_vs = ("%+.0f%%" % (100.0 * (mov / k["k_inc"] - 1.0))) if (mov and k["k_inc"]) else "n/a"
        print("  %-4s %2d/%-2d | %8.1f %8.1f %6.0fs | %8.1f %8.1f %6.0fs | %6s %6s %5.1f"
              % (fam, len(cells), ncert, mlb, mov, mrt or -1,
                 k["k_lb"], k["k_inc"], K_TL, lb_vs, ov_vs, ggap or -1))
    done = len(allcells)
    full_ng = sum(1 for r in allcells if r["cert"] == "ng")
    print("\n  cells banked frzdual2: %d / 27   (%d certified ng)" % (done, full_ng))
    if done < 27:
        print("  (grid still filling -- rerun at completion for the full claim)")
    print("\n  RT NOTE (CLAUDE.md s3 -- NOT a speed claim): K_RT 14400s is K's per-cell TIME LIMIT,")
    print("  HIT at n100 (their MILP is unsolved, 60-77% gap). ourRT is wall our-seconds; the shared")
    print("  budget normalizes 14400 K-s = 5760 our-s at HW 2.5 (d245/d250). Read as 'we reach a")
    print("  tighter bound + a lower OV within a FRACTION of the shared budget', never 'Nx faster'.")
    print("\n  OV-beats-K BURDEN (d663): ourOV < K_best is FAMILY-MEAN on the same instances, NOT")
    print("  per-cell (K has no per-cell n100). Discharge via the n20/n30 per-cell parity cross-check")
    print("  (our derived OV vs K table3 per-instance) BEFORE any 'we beat K OV' claim.")
    print("\n  CLAIM FORM (family-mean granularity, same instances as K): certified ng-LB means are")
    print("  tighter than K's implied LB by the LBvsK margins above; our gaps are ~3-5x below K's")
    print("  published n100 gaps (60-77%). K_best = min(joint, lbbd) = K's better method.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
