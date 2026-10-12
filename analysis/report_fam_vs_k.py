"""Mean OV, mean LB and mean optimality gap (OV-LB)/OV -- OURS vs K -- at family x n-count where K
discloses family, else at K's aggregation level. Read-only.

OURS:  ONE UNIFORM TRACKABLE VARIANT at EVERY size -- frzdual2 per cell (dual incumbent OV + certified
       default-delta LB). We cannot freeze a two-variant grid, so the whole-grid record is the single
       variant that spans n10..n100 (the primal pipeline prim_ens only ran at n10/20/30 and is reported
       separately, NOT blended into this cross-size table).
K:     n10/20/30 per-cell (table3) -> family/size means; K OV = min(joint_bk,lbbd_bk), K LB =
       joint_bk*(1-joint_gap/100) (the joint-model LB, the only one K publish). n100 per FAMILY
       (table6): K OV = min(joint.zIP,lbbd.zIP), K LB = joint.zIP*(1-gap_joint/100). n50 POOL only
       (table4, 1:10): K OV = min(joint,lbbd) bk, K LB = joint_bk*(1-joint_gap/100).

Gap is computed from the two MEANS shown, both sides the same way, so each row's gap is exactly
(meanOV-meanLB)/meanOV. PROXIMITY differs by size (0.0 at 10/20/30/50, 0.1 at 100) and is printed.
"""
import glob
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import k_comparison as K

CELLS = (["C2%02d" % i for i in range(1, 9)] + ["R2%02d" % i for i in range(1, 12)]
         + ["RC2%02d" % i for i in range(1, 9)])
FAMS = (("C", lambda c: c.startswith("C")),
        ("R", lambda c: c.startswith("R") and not c.startswith("RC")),
        ("RC", lambda c: c.startswith("RC")))


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def gap(ov, lb):
    return 100.0 * (ov - lb) / ov if (ov and lb is not None and ov > 0) else None


def our_uniform(size):
    """{cell: (OV, LB)} from the landed uniform artifact (n10/20/30)."""
    p = os.path.join(ROOT, "runs", "oracle", "tep_uniform_n%d.json" % size)
    d = json.load(io.open(p, encoding="utf-8"))
    return {r["cell"]: (r["best"], r.get("our_lb")) for r in d["rows"]}


def our_frzdual(size):
    """{cell: (OV, LB)} from frzdual2 per cell (n50/n100)."""
    import re
    out = {}
    for f in glob.glob(os.path.join(ROOT, "runs", "oracle", "tep_solve_frzdual2_*_n%d.json" % size)):
        m = re.search(r"frzdual2_([A-Z]+\d+)_n%d" % size, os.path.basename(f))
        if not m:
            continue
        c = m.group(1)
        d = json.load(io.open(f, encoding="utf-8"))
        r = d.get("rows", [d])
        r = r[0] if isinstance(r, list) else r
        out[c] = (r.get("ov"), r.get("lb"))
    return out


def k_percell(size):
    """{cell: (K_OV, K_LB)} from table3 per-instance (n10/20/30)."""
    pi = K._kref()["table3"]["per_instance"][str(size)]
    out = {}
    for c, d in pi.items():
        j, l = float(d["joint_bk"]), float(d.get("lbbd_bk") or d["joint_bk"])
        g = float(d.get("joint_gap") or 0.0)
        out[c] = (min(j, l), j * (1.0 - g / 100.0))
    return out


def row(label, n, ours, k_ov, k_lb):
    o_ov, o_lb = mean([x[0] for x in ours]), mean([x[1] for x in ours])
    print("  %-4s %3d | %9s %9s %7s | %9s %9s %7s"
          % (label, n,
             ("%.1f" % o_ov) if o_ov else "-", ("%.1f" % o_lb) if o_lb is not None else "-",
             ("%.1f%%" % gap(o_ov, o_lb)) if gap(o_ov, o_lb) is not None else "-",
             ("%.1f" % k_ov) if k_ov else "-", ("%.1f" % k_lb) if k_lb is not None else "-",
             ("%.1f%%" % gap(k_ov, k_lb)) if gap(k_ov, k_lb) is not None else "-"))


def header(title):
    print("\n%s" % title)
    print("  fam    n |    ourOV    ourLB  ourGap |      KOV     KLB   Kgap")


def by_family(size, ours, kpc):
    """n10/20/30: family + size total, both sides per-cell -> means."""
    for fam, pred in FAMS:
        cs = [c for c in CELLS if pred(c)]
        ov = [ours[c] for c in cs if c in ours]
        kov = mean([kpc[c][0] for c in cs if c in kpc])
        klb = mean([kpc[c][1] for c in cs if c in kpc])
        row(fam, len(ov), ov, kov, klb)
    allc = [ours[c] for c in CELLS if c in ours]
    row("ALL", len(allc), allc, mean([kpc[c][0] for c in CELLS if c in kpc]),
        mean([kpc[c][1] for c in CELLS if c in kpc]))


def main(argv):
    # 10 / 20 / 30 -- family level, K per-cell; OUR side = frzdual2 (the uniform variant), NOT prim_ens
    for size in (10, 20, 30):
        prox = "proximity 0.0" + ("; K proves all 27 -> Kgap~0, our LB loose at this size" if size == 10 else "")
        header("n%d  (family level; %s)" % (size, prox))
        by_family(size, our_frzdual(size), k_percell(size))
    # 100 -- family level, K from table6
    header("n100 (family level; proximity 0.1 -- differs from the others, disclosed)")
    ours = our_frzdual(100)
    t6 = K._kref()["table6"]
    for fam, pred in FAMS:
        cs = [c for c in CELLS if pred(c)]
        ov = [ours[c] for c in cs if c in ours]
        r6 = t6[fam]
        kov = min(r6["joint"]["zIP"], r6["lbbd"]["zIP"])
        klb = r6["joint"]["zIP"] * (1.0 - r6["gap_joint"] / 100.0)
        row(fam, len(ov), ov, kov, klb)
    print("  (n100 size-total omitted: K publish family aggregates only, not a pooled 27-cell OV)")
    # 50 -- K pool only (no family)
    header("n50  (K POOL only -- no family disclosed; K = table4 1:10, proximity inferred, d666)")
    ours50 = our_frzdual(50)
    t4 = {(r["method"]): r for r in K._kref()["table4"] if r.get("size") == 50 and r.get("wls") == "1:10"}
    kj, kl = float(t4["Joint"]["bk"]), float(t4["LBBD"]["bk"])
    kgap_joint = float(t4["Joint"]["gap_imp"])
    k_ov = min(kj, kl); k_lb = kj * (1.0 - kgap_joint / 100.0)
    allc = [ours50[c] for c in CELLS if c in ours50]
    row("ALL", len(allc), allc, k_ov, k_lb)
    print("\nGap = (meanOV - meanLB)/meanOV, each side with its OWN OV and LB. K LB = joint-model LB")
    print("(joint_bk*(1-joint_gap/100)); K publish no LBBD lower bound (d668).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
