"""Gap-attack report: per cell/size, the THINNED gap after the overnight campaign vs the frzdual2
baseline and K's proven optima. best LB = max over {frzdual2, fgd<delta>}; best OV = min over
{frzdual2 derived, fgd<delta> derived, prim3gk grow-k primal}; gap = (bestOV-bestLB)/bestLB.
Run SINGLE-TENANT after the campaign (or any time -- read-only; shows progress so far).
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
    for size in (10, 20, 30, 50):
        pi = K._kref()["table3"]["per_instance"].get(str(size), {}) if size in (10, 20, 30) else {}
        print("\n" + "=" * 96)
        print("GAP-ATTACK | n%d  (baseline frzdual2 gap  ->  thinned gap; K opt where proven)" % size)
        print("=" * 96)
        print("  %-6s %8s %8s | %8s %8s %7s | %7s %7s  %s"
              % ("cell", "baseLB", "baseOV", "bestLB", "bestOV", "gap%", "basegap", "Kopt", "fg deltas"))
        n = thinned = 0; base_sum = thin_sum = 0.0
        for c in CELLS:
            base = rec("frzdual2", c, size)
            if base is None:
                continue
            lbs = [base.get("lb")]; ovs = [base.get("ov")]; ds = []
            for p in sorted(glob.glob(os.path.join(ROOT, "runs", "oracle", "tep_solve_fgd*_%s_n%d.json" % (c, size)))):
                tag = os.path.basename(p).split("_")[2]           # fgd<delta>
                r = rec(tag, c, size)
                if r:
                    lbs.append(r.get("lb")); ovs.append(r.get("ov")); ds.append(tag.replace("fgd", ""))
            pg = rec("prim3gk", c, size)
            if pg and pg.get("ov") is not None:
                ovs.append(pg["ov"])
            lbs = [x for x in lbs if x is not None]; ovs = [x for x in ovs if x is not None]
            if not lbs or not ovs:
                continue
            bestLB = max(lbs); bestOV = min(ovs)
            basegap = 100.0 * (base["ov"] - base["lb"]) / base["lb"] if (base.get("ov") and base.get("lb")) else None
            gap = 100.0 * (bestOV - bestLB) / bestLB
            kopt = pi.get(c, {}).get("joint_bk")
            n += 1; base_sum += (basegap or 0); thin_sum += gap
            if basegap and gap < basegap - 0.5:
                thinned += 1
            print("  %-6s %8.1f %8.1f | %8.1f %8.1f %7.1f | %6.1f%% %7s  %s"
                  % (c, base["lb"], base["ov"], bestLB, bestOV, gap, basegap or -1,
                     ("%.1f" % kopt) if kopt else "-", ",".join(ds) or "(none yet)"))
        if n:
            print("  --- n=%d | mean gap %.1f%% -> %.1f%% | %d cells thinned" % (n, base_sum/n, thin_sum/n, thinned))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
