"""Per size (n10/20/30): worst OV loss by VALUE, worst OV loss by PERCENT, and #wins -- ensemble
primal (prim_ens) vs K's BEST incumbent (min joint/lbbd, table3). loss = ourOV - K_best (>0 = above
K); win = ourOV < K_best. Single-tenant, read-only.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import k_comparison as K

CELLS = (["C2%02d" % i for i in range(1, 9)] + ["R2%02d" % i for i in range(1, 12)]
         + ["RC2%02d" % i for i in range(1, 9)])


def ov_of(cell, size):
    p = os.path.join(ROOT, "runs", "oracle", "tep_solve_prim_ens_%s_n%d.json" % (cell, size))
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding="utf-8")); r = d.get("rows", [d]); r = r[0] if isinstance(r, list) else r
    return r.get("ov")


def main(argv):
    print("  size |  worst OV loss (value)        |  worst OV loss (percent)       | wins")
    print("  -----+-------------------------------+--------------------------------+-----")
    for size in (10, 20, 30):
        pi = K._kref()["table3"]["per_instance"].get(str(size), {})
        losses = []; wins = 0; n = 0
        for c in CELLS:
            ov = ov_of(c, size); k = pi.get(c, {})
            if ov is None or not k:
                continue
            jb, lb = k.get("joint_bk"), k.get("lbbd_bk")
            kbest = min([x for x in (jb, lb) if x is not None])
            n += 1
            if ov < kbest - 0.05:
                wins += 1
            elif ov > kbest + 0.05:
                losses.append((c, ov - kbest, 100.0 * (ov / kbest - 1.0), ov, kbest))
        wv = max(losses, key=lambda t: t[1]) if losses else None
        wp = max(losses, key=lambda t: t[2]) if losses else None
        sv = ("%-6s +%6.1f (OV %.1f vs K %.1f)" % (wv[0], wv[1], wv[3], wv[4])) if wv else "(none)"
        sp = ("%-6s +%5.1f%% (OV %.1f vs K %.1f)" % (wp[0], wp[2], wp[3], wp[4])) if wp else "(none)"
        print("  n%-3d | %-29s | %-30s | %d/%d" % (size, sv, sp, wins, n))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
