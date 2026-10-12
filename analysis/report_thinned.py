"""Thinned-gap report (d676): per cell/size (n10/20/30), the gap after BOTH levers --
best LB = max over {frzdual2, finer-grain fgd<delta>}; best OV = min over {frzdual2 derived,
ensemble prim_ens}. gap = (bestOV-bestLB)/bestLB, vs the frzdual2 baseline gap, with K's proven
optimum for reference. Separates how much is closed vs the IRREDUCIBLE relaxation residual
(best LB still << opt even at finest grain). Honest: names cells that stay wide and why.
Single-tenant, read-only (shows progress so far).
"""
import glob
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
    for size in (10, 20, 30):
        pi = K._kref()["table3"]["per_instance"].get(str(size), {})
        print("\n" + "=" * 92)
        print("THINNED GAP | n%d  (frzdual2 baseline -> both-lever; Kopt ref; LB-residual to opt)" % size)
        print("=" * 92)
        print("  %-6s %7s %7s | %7s %7s %6s | %6s %7s  %s"
              % ("cell", "bestLB", "bestOV", "base%", "thin%", "Kopt", "LBvsopt", "verdict", "fg"))
        n = 0; bsum = tsum = 0.0; thin = irred = 0
        for c in CELLS:
            base = rec("frzdual2", c, size)
            if base is None or base.get("lb") is None:
                continue
            lbs = [base["lb"]]; ds = []
            for p in sorted(glob.glob(os.path.join(ROOT, "runs", "oracle", "tep_solve_fgd*_%s_n%d.json" % (c, size)))):
                tag = os.path.basename(p).split("_")[2]
                r = rec(tag, c, size)
                if r and r.get("lb") is not None:
                    lbs.append(r["lb"]); ds.append(tag.replace("fgd", ""))
            ovs = [base.get("ov")]
            pe = rec("prim_ens", c, size)
            if pe and pe.get("ov") is not None:
                ovs.append(pe["ov"])
            ovs = [x for x in ovs if x is not None]
            if not ovs:
                continue
            bestLB = max(lbs); bestOV = min(ovs); kopt = pi.get(c, {}).get("joint_bk")
            basegap = 100.0 * (base["ov"] - base["lb"]) / base["lb"] if base.get("ov") else None
            thingap = 100.0 * (bestOV - bestLB) / bestLB
            lb_vs_opt = (100.0 * (bestLB / kopt - 1.0)) if kopt else None  # how far best LB is below opt (neg)
            n += 1; bsum += (basegap or 0); tsum += thingap
            # verdict: THIN if gap<5%; else if OV~opt but LB loose -> LB-RESIDUAL (irreducible-ish)
            if thingap < 5.0:
                verdict = "THIN"; thin += 1
            elif kopt and bestOV <= kopt * 1.01:
                verdict = "LB-resid"; irred += 1     # OV at opt, gap is the loose relaxation
            else:
                verdict = "wide"
            print("  %-6s %7.1f %7.1f | %6s %6.1f %6s | %6s %8s  %s"
                  % (c, bestLB, bestOV, ("%.1f" % basegap) if basegap else "-", thingap,
                     ("%.1f" % kopt) if kopt else "-",
                     ("%+.0f%%" % lb_vs_opt) if lb_vs_opt is not None else "-", verdict, ",".join(ds) or "-"))
        if n:
            print("  --- n=%d | mean gap %.1f%% -> %.1f%% | THIN(<5%%) %d | LB-residual(OV@opt,LB loose) %d"
                  % (n, bsum / n, tsum / n, thin, irred))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
