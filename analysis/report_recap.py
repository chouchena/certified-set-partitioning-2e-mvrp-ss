"""Recap of the BEST PRIMAL VARIANT (ensemble prim_ens) over n10/20/30: OV and LB vs K.
OV = prim_ens derived incumbent (verifier3-clean). LB = the FROZEN dual LB from the same run
(default_delta, fast pricer -- NOT refined). K: opt/best incumbent (table3 joint_bk) and K's
joint-model LB (joint_bk*(1-joint_gap/100); = opt where proven). Single-tenant, read-only.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import k_comparison as K

CELLS = (["C2%02d" % i for i in range(1, 9)] + ["R2%02d" % i for i in range(1, 12)]
         + ["RC2%02d" % i for i in range(1, 9)])


def rec(cell, size):
    p = os.path.join(ROOT, "runs", "oracle", "tep_solve_prim_ens_%s_n%d.json" % (cell, size))
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding="utf-8")); r = d.get("rows", [d]); r = r[0] if isinstance(r, list) else r
    return r


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def main(argv):
    for size in (10, 20, 30):
        pi = K._kref()["table3"]["per_instance"].get(str(size), {})
        rows = []
        for c in CELLS:
            r = rec(c, size)
            k = pi.get(c, {})
            if r is None or r.get("ov") is None or not k:
                continue
            jb = k.get("joint_bk"); kg = k.get("joint_gap") or 0.0
            lb_k = k.get("lbbd_bk")
            kbest = min([x for x in (jb, lb_k) if x is not None])   # K's BEST incumbent (not just joint)
            klb = jb * (1.0 - kg / 100.0)                           # K's published (joint-model) LB
            rows.append((c, r.get("ov"), r.get("lb"), kbest, klb))
        if not rows:
            print("\nn%d: no prim_ens records" % size); continue
        mov = mean([x[1] for x in rows]); mlb = mean([x[2] for x in rows])
        mko = mean([x[3] for x in rows]); mkl = mean([x[4] for x in rows])
        reach = sum(1 for x in rows if x[1] <= x[3] * 1.01)
        beat = sum(1 for x in rows if x[1] < x[3] - 0.05)
        print("\n=== n%d | best primal variant (prim_ens) vs K | %d cells ===" % (size, len(rows)))
        print("              our OV     our LB  |   K best   K LB")
        print("  mean     %9.1f %9.1f  | %8.1f %8.1f" % (mov, mlb, mko, mkl))
        print("  vs K      OV %+.1f%%  LB %+.1f%% (our LB vs K joint LB)" % (100*(mov/mko-1), 100*(mlb/mkl-1)))
        print("  reach K opt/best (<=1%%): %d/%d   |   beat K incumbent: %d/%d" % (reach, len(rows), beat, len(rows)))
        # cells NOT reaching + cells where we beat K
        miss = [(c, ov, ko, 100*(ov/ko-1)) for c, ov, lb, ko, kl in rows if ov > ko * 1.01]
        if miss:
            print("  OV not at K opt/best: " + ", ".join("%s %+.1f%%" % (c, g) for c, ov, ko, g in miss))
        beats = [(c, 100*(ov/ko-1)) for c, ov, lb, ko, kl in rows if ov < ko - 0.05]
        if beats:
            print("  OV beats K incumbent: " + ", ".join("%s %+.1f%%" % (c, g) for c, g in beats))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
