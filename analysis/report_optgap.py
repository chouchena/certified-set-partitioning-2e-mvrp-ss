"""MAIN NARRATIVE METRIC: proven optimality gap (OV-LB)/OV -- ours vs K -- on the OPEN cells (K did
not prove). n20/n30 per-cell (table3); n100 per-family (table6). ours: prim_ens OV where it exists
(n20/n30), else frzdual2 byproduct OV (n100); LB = frozen dual. K: best incumbent min(joint,lbbd) and
K's joint-model LB -> K's tightest published bracket; also K's reported joint gap for reference.
Open = K joint_gap > 1%. Single-tenant, read-only.
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


def ov_lb(tag, cell, size):
    p = os.path.join(ROOT, "runs", "oracle", "tep_solve_%s_%s_n%d.json" % (tag, cell, size))
    if not os.path.exists(p):
        return None, None
    d = json.load(open(p, encoding="utf-8")); r = d.get("rows", [d]); r = r[0] if isinstance(r, list) else r
    return r.get("ov"), r.get("lb")


def med(xs):
    xs = sorted(x for x in xs if x is not None)
    return xs[len(xs) // 2] if xs else None


def main(argv):
    # n20 / n30 per-cell
    for size in (20, 30):
        pi = K._kref()["table3"]["per_instance"].get(str(size), {})
        ours = []; k_best = []; k_joint = []; nopen = 0
        for c in CELLS:
            k = pi.get(c, {})
            if not k:
                continue
            jb, lbb, jg = k.get("joint_bk"), k.get("lbbd_bk"), (k.get("joint_gap") or 0.0)
            if jg <= 1.0:            # K-proven / near-proven -> calibration, not the open set
                continue
            ov, lb = ov_lb("prim_ens", c, size)
            if ov is None:
                ov, lb = ov_lb("frzdual2", c, size)
            if ov is None or lb is None:
                continue
            nopen += 1
            ours.append(100.0 * (ov - lb) / ov)
            kb = min([x for x in (jb, lbb) if x is not None]); klb = jb * (1.0 - jg / 100.0)
            k_best.append(100.0 * (kb - klb) / kb)
            k_joint.append(jg)
        print("n%-3d OPEN (%d cells): OUR median gap %.1f%%  |  K best-bracket %.1f%%  |  K reported joint %.1f%%"
              % (size, nopen, med(ours) or -1, med(k_best) or -1, med(k_joint) or -1))
    # n100 per-family (all open)
    t6 = K._kref()["table6"]
    print("n100 (all open), per family, cell-weighted:")
    owg = []; okg = []
    for fam in ("C", "R", "RC"):
        cells = [c for c in CELLS if (c.startswith("RC") if fam == "RC" else c.startswith(fam) and not c.startswith("RC"))]
        gs = []
        for c in cells:
            ov, lb = ov_lb("frzdual2", c, 100)
            if ov and lb:
                gs.append(100.0 * (ov - lb) / ov)
        og = sum(gs) / len(gs) if gs else None
        row = t6[fam]; kbest = min(row["joint"]["zIP"], row["lbbd"]["zIP"])
        klb = row["joint"]["zIP"] * (1 - row["gap_joint"] / 100.0)
        kg = 100.0 * (kbest - klb) / kbest
        owg += [og] * FAMN[fam]; okg += [kg] * FAMN[fam]
        print("   %-3s  our %.1f%%  |  K best-bracket %.1f%%  (K reported joint %.1f%%)"
              % (fam, og or -1, kg, row["gap_joint"]))
    print("   n100 cell-weighted:  our %.1f%%  |  K best-bracket %.1f%%"
          % (sum(owg)/len(owg), sum(okg)/len(okg)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
