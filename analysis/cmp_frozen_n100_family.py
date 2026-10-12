"""Two-leg strength over the COMPLETE frozen n100 grid (27 cells), at K's Table 6 FAMILY granularity.

Reads the frozen two-legs citable artifacts (tep_solve_frzprimal_<cell>_n100.json for OV, and
tep_solve_frzdual_<cell>_n100.json for LB) banked by the frozen campaign, groups by family, and
compares family MEANS to K's Table 6 (incumbent = min(joint, lbbd) per d1; derived LB =
joint x (1 - gap_joint/100)). Prints only; the full-family comparison K actually publishes at n100.
Run AFTER the campaign completes and nothing is banking (it opens no solver, but keep it single-leg).
"""
import glob
import json
import os
import sys

sys.path.insert(0, "analysis")
import k_comparison as K

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CELLS = (["C20%d" % i for i in range(1, 9)]
         + ["R20%d" % i for i in range(1, 10)] + ["R210", "R211"]
         + ["RC20%d" % i for i in range(1, 9)])
FAM = lambda c: "RC" if c.startswith("RC") else c[0]


def _row(tag, cell):
    p = os.path.join(ROOT, "runs", "oracle", "tep_solve_%s_%s_n100.json" % (tag, cell))
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding="utf-8"))
    r = d.get("rows", [d])
    return (r[0] if isinstance(r, list) else r), d


def main():
    kref = K._kref()
    t6 = kref["table6"]
    per = {}   # cell -> (ov, lb, certified_bool)
    missing = []
    for c in CELLS:
        pr = _row("frzprimal", c)
        dr = _row("frzdual", c)
        if pr is None or dr is None:
            missing.append(c); continue
        ov = pr[0].get("ov")
        lb = dr[0].get("lb")
        cert = dr[0].get("certificate") in ("elementary", "ng")
        per[c] = (ov, lb, cert)
    print("=== frozen n100 two-leg strength (%d/27 cells; FAMILY means vs K Table 6) ===" % len(per))
    if missing:
        print("  MISSING (campaign incomplete): %s" % ", ".join(missing))
    print("  %-3s %4s | %9s %10s %7s | %9s %10s %7s | %5s"
          % ("fam", "n", "ourOV", "K_inc", "dOV%", "ourLB", "K_LB", "dLB%", "cert"))
    for fam in ("C", "R", "RC"):
        cs = [c for c in per if FAM(c) == fam]
        if not cs:
            continue
        ovs = [per[c][0] for c in cs if per[c][0] is not None]
        lbs = [per[c][1] for c in cs if per[c][1] is not None]
        ncert = sum(1 for c in cs if per[c][2])
        our_ov = sum(ovs) / len(ovs) if ovs else None
        our_lb = sum(lbs) / len(lbs) if lbs else None
        row = t6[fam]
        k_inc = min(row["joint"]["zIP"], row["lbbd"]["zIP"])
        k_lb = row["joint"]["zIP"] * (1.0 - row["gap_joint"] / 100.0)
        dov = 100.0 * (our_ov / k_inc - 1.0) if our_ov else None
        dlb = 100.0 * (our_lb / k_lb - 1.0) if our_lb else None
        print("  %-3s %4d | %9.1f %10.1f %+6.1f%% | %9.1f %10.1f %+6.1f%% | %d/%d"
              % (fam, len(cs), our_ov, k_inc, dov, our_lb, k_lb, dlb, ncert, len(cs)))
    print("\n  dOV%% <0 = our family-mean incumbent below K's (we win the OV leg);")
    print("  dLB%% >0 = our family-mean LB above K's derived LB (we win the LB leg);")
    print("  cert = cells whose dual CERTIFIED a tight LB (else AB4 floor).")
    # per-cell detail, for the record
    print("\n  per-cell: cell  ov  lb  cert")
    for c in CELLS:
        if c in per:
            ov, lb, cert = per[c]
            print("    %-6s %9s %9s %s"
                  % (c, ("%.1f" % ov) if ov else "-", ("%.1f" % lb) if lb else "-",
                     "certified" if cert else "AB4"))


if __name__ == "__main__":
    main()
