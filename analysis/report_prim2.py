"""Sampled primal comparison reporter (PREREG_n100_primal_capped_variants.md, d661).
Per sample cell, lays the 4 tail variants (P0/P-sel/P-alns/P-full) beside:
  * the frozen primal baseline (frzprimal) OV,
  * the inherited frzdual2 derived OV (what P0 warm-starts from),
  * our certified frzdual2 ng-LB (-> gap),
plus the K-blind diagnostics nCars (fleet-basin) and gap-to-our-LB.

Answers the operational question the smoke exists for: does ANY tail search move OV off P0
(the inherited incumbent), and does any beat the frozen primal? Makes NO comparative claim
(1 seed) -- a published X>Y needs the d8 >=8-seed paired design.

Run SINGLE-TENANT (after the smoke python has exited).
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CELLS = ["C204", "R207", "RC204"]
VARIANTS = ["P0", "P-sel", "P-alns", "P-full"]


def _rec(tag, cell, size=100):
    p = os.path.join(ROOT, "runs", "oracle", "tep_solve_%s_%s_n%d.json" % (tag, cell, size))
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding="utf-8"))
    r = d.get("rows", [d]); r = r[0] if isinstance(r, list) else r
    rt = d.get("_rt") or {}
    return {"ov": r.get("ov"), "lb": r.get("lb"), "nCars": r.get("nCars"),
            "wall_s": rt.get("wall_s") or r.get("wall_s"), "cert": r.get("certificate")}


def pct(a, b):
    return ("%+.2f%%" % (100.0 * (a / b - 1.0))) if (a and b) else "   n/a"


def main(argv):
    size = int(argv[1]) if len(argv) > 1 else 100
    print("=== prim2 sampled comparison | n%d (1 seed -- sizing/operational, NOT a claim) ===\n" % size)
    moved_any = beat_frozen_any = False
    for cell in CELLS:
        fp = _rec("frzprimal", cell, size)         # frozen primal baseline
        du = _rec("frzdual2", cell, size)          # inherited incumbent + certified LB
        base_ov = fp["ov"] if fp else None
        inh_ov = du["ov"] if du else None
        lb = du["lb"] if du else None
        print("--- %s | frozen-primal OV %s | inherited(frzdual2) OV %s | LB %s (cert=%s) ---"
              % (cell, base_ov, inh_ov, lb, (du or {}).get("cert")))
        print("    %-7s %10s %6s %8s %10s %10s %9s" % ("variant", "OV", "nCars", "wall_s", "vs frozen", "vs P0", "gap-to-LB"))
        p0 = _rec("prim2_P0", cell, size)
        p0_ov = p0["ov"] if p0 else None
        for V in VARIANTS:
            r = _rec("prim2_%s" % V, cell, size)
            if r is None:
                print("    %-7s %10s" % (V, "(not run)")); continue
            gap = ("%.2f%%" % (100.0 * (r["ov"] - lb) / lb)) if (r["ov"] and lb) else "n/a"
            print("    %-7s %10.2f %6s %8s %10s %10s %9s"
                  % (V, r["ov"], r["nCars"], ("%.0f" % r["wall_s"]) if r["wall_s"] else "-",
                     pct(r["ov"], base_ov), pct(r["ov"], p0_ov), gap))
            if V != "P0" and p0_ov and r["ov"] < p0_ov - 1e-6:
                moved_any = True
            if base_ov and r["ov"] < base_ov - 1e-6:
                beat_frozen_any = True
        print()
    print("SUMMARY (1-seed, operational):")
    print("  any tail variant moved OV below P0 (inherited incumbent)?  %s" % ("YES" if moved_any else "no -- P0 at/near ceiling (d653 for-free channel)"))
    print("  any variant beat the frozen primal?                        %s" % ("YES" if beat_frozen_any else "no"))
    print("  -> informs the tail variant to wire; a published X>Y needs the d8 >=8-seed paired design.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
