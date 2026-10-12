"""Runtime against the predecessors', per size, normalised — and time-to-best wherever they publish it. (2026-09-27)

WHAT IS AND IS NOT COMPARABLE, stated before any number (CLAUDE.md section 3, validation/RT_LEG_DESIGN.md):

  * RT_LEG_DESIGN.md section 4 FORBIDS the ratio of our seconds to their run time -- 'we match their solution in
    2 percent of the time' is arithmetically available and must not be made: their cap buys an exact method that
    also produces dual bounds and proofs, our budget buys incumbents; our budget is a CHOICE and theirs is a limit
    their method consumed (73-93 percent at |C| = 20 and 30); and it is a raw-seconds claim in disguise. This table
    therefore reports our consumption of the SHARED cap as a fairness precondition, prints their published figures
    as CONTEXT, and makes no speed claim. (Written after I made exactly that forbidden claim on 2026-09-27 08:12.)
  * Direction of the factor, verified: per core we are FASTER (RT_LEG_DESIGN section 3), so 5,760 our-seconds tie
    their 14,400 at factor 2.5, and OUR seconds are multiplied by the factor to reach their scale. 2.5 is the
    strictest reading -- it inflates our charge -- and the benefit of the factor cannot be taken in the budget and
    denied in the report.
  * Their INC TIME is time-to-best-incumbent, published per instance at |C| = 20 and 30 and as a summary at 10.
    Ours is the charged seconds up to and including the stage that produced our final incumbent, from the same
    artifacts the ledger reads. This IS like-for-like in definition, and still not a speed claim: they keep
    searching after their incumbent, we stop.
  * HARDWARE. Their 4 CPUs Intel Xeon Gold 5218 @ 2.30 GHz against our Core Ultra 7 258V. One our-second is worth
    `factor` of their seconds; no single factor is defensible, so every figure is given across HW_FACTORS
    (1.0, 1.5, 2.0, 2.5) and the headline uses 2.5, the least favourable to us.
  * Threads: every model we solve runs on 1 thread (the small-size master IP on 2); they had 4 CPUs.
  * Our seconds cover BOTH legs (bound + primal). Attempts whose value is not reported are excluded here and
    counted separately, as in runs/oracle/tep_insights.json.

    python analysis/tep_runtime_vs_k.py
"""
import glob
import io
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped
from bound_certificate import certified
import run_full_grid as G

CELLS = ["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)] + ["RC%d" % i for i in range(201, 209)]
ST = ("floor", "ceil", "refine", "alns", "selchain", "forced")


def load(p):
    return json.load(io.open(p, encoding="utf-8")) if os.path.exists(p) else None


def our_cell(cell, size):
    """(charged seconds, seconds to our final incumbent, the stage that produced it, unstamped stages)."""
    vals, secs = {}, {}
    for s in ST:
        d = load(os.path.join(ROOT, "runs", "postpass", "" if s == "floor" else s, "ownwater_%s_n%d.json" % (cell, size)))
        if d:
            vals[s] = float(d["objVal"]); secs[s] = d.get("secs")
    if not vals:
        return None
    best = min(vals, key=vals.get)
    order = [s for s in ST if s in vals]
    upto = order[:order.index(best) + 1]
    prim = sum(v for v in secs.values() if isinstance(v, (int, float)))
    ttb = sum(secs[s] for s in upto if isinstance(secs.get(s), (int, float)))
    # CHARGE EVERY WIDTH WE RAN, not only the one that won. The reported bound is the maximum over the proven
    # widths, and a maximum cannot be selected post hoc without paying for the search (d245/d246/d250).
    # 2026-09-27: the first version of this table charged the default width alone and understated n30 by ~12%.
    pats = ([ "tep_cg_bound_%s.json", "tep_cg_bound_%s_ip.json", "tep_cg_bound_%s_d10.json", "tep_cg_bound_%s_d5.json"]
            if size == 100 else
            ["tep_cg_bound_%s_n" + str(size) + ".json", "tep_cg_bound_%s_n" + str(size) + "_ip.json",
             "tep_cg_bound_%s_n" + str(size) + "_d10.json", "tep_cg_bound_%s_n" + str(size) + "_d10_ip.json",
             "tep_cg_bound_%s_n" + str(size) + "_d5.json", "tep_cg_bound_%s_n" + str(size) + "_d5_ip.json"])
    files = [load(os.path.join(ROOT, "runs", "oracle", pp % cell)) for pp in pats]
    if size == 100:
        files += [load(f) for f in glob.glob(os.path.join(ROOT, "runs", "oracle", "tep_easy_reduction_%s_n100_k*.json" % cell))]
    files = [x for x in files if x and not x.get("primal_rounding")]
    bnd = sum((x.get("secs") or 0) for x in files if certified(x))
    bnd_abandoned = sum((x.get("secs") or 0) for x in files if not certified(x))
    unst = [s for s in vals if not isinstance(secs.get(s), (int, float))]
    ttb_ok = not any(s in unst for s in upto)   # a time-to-best that sums over an unstamped stage is missing data, not a number
    return dict(cell=cell, charged=prim + bnd, charged_with_abandoned=prim + bnd + bnd_abandoned, primal=prim, bound=bnd,
                bound_abandoned=bnd_abandoned, ttb=(ttb if ttb_ok else None), ttb_ok=ttb_ok, best_stage=best, unstamped=unst)


def main():
    k = load(os.path.join(ROOT, "data", "karademir2025", "k_reference.json"))
    t3 = k["table3"]; out = {}
    print(__doc__.split("\n\n")[1])
    print("\n%-5s %8s | %-28s | %-34s | %s" % ("size", "cells", "OURS, our-seconds", "OURS in THEIR seconds (factor)", "THEIRS, their seconds (published)"))
    print("%-5s %8s | %8s %8s %9s | %10s %10s %10s | %5s | %s" % ("", "", "median", "max", "to best", "x1.0", "x2.0", "x2.5", "cap", "CONTEXT ONLY: joint run / inc | lbbd run / inc"))
    for n in (10, 20, 30, 50, 100):
        rows = [r for r in (our_cell(c, n) for c in CELLS) if r]
        if not rows: continue
        med = st.median(r["charged"] for r in rows); mx = max(r["charged"] for r in rows)
        mxa = max(r["charged_with_abandoned"] for r in rows); mxc = max(rows, key=lambda r: r["charged"])["cell"]
        tt = [r["ttb"] for r in rows if r["ttb_ok"]]
        ttb = st.median(tt) if tt else None
        s3 = t3.get("summary", {}).get(str(n))
        kt = ("%6.0f / %6.0f | %6.0f / %6.0f" % (s3["joint"]["run_time"], s3["joint"]["inc_time"], s3["lbbd"]["run_time"], s3["lbbd"]["inc_time"])) if s3 else "not published at this size (cap 14,400 s)"
        print("n%-4d %8d | %8.0f %8.0f%-8s %9s | %10.0f %10.0f %10.0f | %5.1f%% | %s" % (n, len(rows), med, mx, (" (%s)" % mxc), ("%.0f (%d cells)" % (ttb, len(tt))) if tt else "n/a", med * 1.0, med * 2.0, med * 2.5, 100 * med * 2.5 / 14400.0, kt))
        out["n%d" % n] = dict(cells=len(rows), median_our_s=med, max_our_s=mx, max_cell=mxc, max_our_s_with_abandoned=mxa, median_ttb_our_s=ttb,
                              median_their_s={str(f): med * f for f in G.HW_FACTORS},
                              k_summary=s3, rows=rows,
                              unstamped_cells=[r["cell"] for r in rows if r["unstamped"]])
    print("\nTIME TO BEST, per instance, where they publish it (their seconds; ours x2.5 to their scale):")
    for n in (20, 30):
        per = t3.get("per_instance", {}).get(str(n), {})
        rows = [r for r in (our_cell(c, n) for c in CELLS) if r and r["ttb_ok"] and c_ok(per, r["cell"])]
        if not rows:
            print("  n%-4d NO cell has a stamped time-to-best (every candidate stage predates the secs stamp) -- run analysis/tep_timing_backfill.py --size %d" % (n, n)); continue
        ours = [r["ttb"] * 2.5 for r in rows]
        kj = [float(per[r["cell"]]["joint_inc_time"]) for r in rows]
        kl = [float(per[r["cell"]]["lbbd_inc_time"]) for r in rows]
        faster = sum(1 for a, b in zip(ours, kl) if a < b)
        print("  n%-4d %2d cells | ours median %6.0f s, max %7.0f | their LBBD median %6.0f, max %7.0f | their Joint median %7.0f, max %7.0f | ours sooner on %d of %d vs LBBD"
              % (n, len(rows), st.median(ours), max(ours), st.median(kl), max(kl), st.median(kj), max(kj), faster, len(rows)))
        out["n%d" % n]["ttb_comparison"] = dict(cells=len(rows), ours_their_scale_median=st.median(ours),
                                                lbbd_median=st.median(kl), joint_median=st.median(kj), ours_sooner_than_lbbd=faster)
    uns = sorted({c for v in out.values() for c in v.get("unstamped_cells", [])})
    print("\n  CAVEAT: %d cell(s) carry at least one stage whose seconds were never stamped (the earliest floor artifacts); their charge is understated." % len(uns))
    print("  The cap column is our charge as a share of the SHARED 14,400 s cap at factor 2.5 -- a fairness precondition.")
    print("  Their columns are CONTEXT: an exact method to proof or cap, producing bounds and proofs as well as incumbents.")
    print("  NO SPEED CLAIM IS MADE OR LICENSED BY THIS TABLE (RT_LEG_DESIGN section 4).")
    p = os.path.join(ROOT, "runs", "oracle", "tep_runtime_vs_k.json")
    json.dump(stamped(out), io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    return 0


def c_ok(per, cell):
    return cell in per and per[cell].get("lbbd_inc_time") is not None


if __name__ == "__main__":
    sys.exit(main())
